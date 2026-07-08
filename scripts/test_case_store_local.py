"""Offline smoke test for the case memory (self-improving loop).

No GCP credentials or google-cloud-bigquery install required: a fake bigquery
module is injected, so this validates the case_store contract (default-off,
row shapes, outcome labeling, never-raises) deterministically.

Usage:
    python scripts/test_case_store_local.py
"""
import datetime
import importlib
import os
import sys
import types

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "packages", "agent", "src")
)

TABLE = "demo-project.autosre_memory.cases"


# ---------------------------------------------------------------- fake bigquery
class _FakeRow(dict):
    def __getitem__(self, key):
        return dict.get(self, key)


class _FakeJob:
    def __init__(self, rows):
        self._rows = rows

    def result(self, timeout=None):
        return [_FakeRow(r) for r in self._rows]


class _FakeClient:
    inserted: list = []
    query_rows: list = []
    fail_insert = False

    def __init__(self, project=None):
        self.project = project

    def insert_rows_json(self, table, rows, timeout=None):
        if _FakeClient.fail_insert:
            raise RuntimeError("simulated BigQuery outage")
        _FakeClient.inserted.extend(rows)
        return []

    def query(self, sql, job_config=None):
        return _FakeJob(_FakeClient.query_rows)


def _install_fake_bigquery():
    fake = types.ModuleType("google.cloud.bigquery")
    fake.Client = _FakeClient
    fake.ScalarQueryParameter = lambda *a, **k: None
    fake.QueryJobConfig = lambda *a, **k: None
    # Self-sufficient: also fabricate the google / google.cloud namespace
    # packages when the real ones are not installed (fresh machine, no venv).
    try:
        import google.cloud as gcloud_pkg  # noqa: F401 - real namespace if available
    except ImportError:
        g = sys.modules.setdefault("google", types.ModuleType("google"))
        gc = types.ModuleType("google.cloud")
        sys.modules["google.cloud"] = gc
        g.cloud = gc
    sys.modules["google.cloud.bigquery"] = fake
    sys.modules["google.cloud"].bigquery = fake


# ------------------------------------------------------------------- test cases
def test_disabled_is_noop(cs):
    os.environ.pop("AUTOSRE_CASES_TABLE", None)
    importlib.reload(cs)
    cs.record_diagnosis({"root_cause": "x"}, source="manual", service="svc", duration_s=1.0)
    cs.record_resolution(1, True, 2.0)
    out = cs.recall_similar_cases("svc")
    ok = (
        not cs.enabled()
        and _FakeClient.inserted == []
        and out["ok"] is True
        and out["enabled"] is False
        and out["cases"] == []
    )
    return ok, f"enabled={cs.enabled()} recall={out}"


def test_record_diagnosis_row(cs):
    os.environ["AUTOSRE_CASES_TABLE"] = TABLE
    importlib.reload(cs)
    _FakeClient.inserted = []
    diagnosis = {
        "root_cause": "DATABASE_URL is missing from the deployed config",
        "missing_env_var": "DATABASE_URL",
        "action": "fix_pr",
        "confidence": 1.0,
        "pr_url": "https://github.com/x/y/pull/7",
        "pr_number": 7,
        "user_reports_summary": "落ちてるという報告",
    }
    cs.record_diagnosis(diagnosis, source="pubsub", service="sida-target", duration_s=88.4)
    if len(_FakeClient.inserted) != 1:
        return False, f"expected 1 row, got {len(_FakeClient.inserted)}"
    row = _FakeClient.inserted[0]
    ok = (
        row["kind"] == "diagnosis"
        and row["service"] == "sida-target"
        and row["source"] == "pubsub"
        and row["missing_env_var"] == "DATABASE_URL"
        and row["pr_number"] == 7
        and row["confidence"] == 1.0
        and row["duration_s"] == 88.4
        and row["case_id"]
        and row["ts"]
    )
    return ok, f"row={row}"


def test_skips_unparseable_diagnosis(cs):
    _FakeClient.inserted = []
    cs.record_diagnosis({"error": "parse_failed"}, source="manual", service="svc", duration_s=1.0)
    cs.record_diagnosis({}, source="manual", service="svc", duration_s=1.0)
    return _FakeClient.inserted == [], f"inserted={_FakeClient.inserted}"


def test_record_resolution_row(cs):
    _FakeClient.inserted = []
    cs.record_resolution(7, True, 34.2)
    row = _FakeClient.inserted[0] if _FakeClient.inserted else {}
    ok = (
        row.get("kind") == "resolution"
        and row.get("pr_number") == 7
        and row.get("recovered") is True
        and row.get("duration_s") == 34.2
    )
    return ok, f"row={row}"


def test_insert_failure_never_raises(cs):
    _FakeClient.fail_insert = True
    try:
        cs.record_diagnosis({"root_cause": "x"}, source="manual", service="svc", duration_s=1.0)
        cs.record_resolution(1, False, 1.0)
        ok, detail = True, "no exception propagated"
    except Exception as e:  # noqa: BLE001
        ok, detail = False, f"raised {type(e).__name__}: {e}"
    _FakeClient.fail_insert = False
    return ok, detail


def test_recall_outcome_labels(cs):
    ts = datetime.datetime(2026, 7, 8, 12, 0, tzinfo=datetime.timezone.utc)
    base = {
        "ts": ts,
        "source": "pubsub",
        "root_cause": "missing DATABASE_URL",
        "missing_env_var": "DATABASE_URL",
        "action": "fix_pr",
        "confidence": 1.0,
        "pr_url": "https://github.com/x/y/pull/7",
        "pr_number": 7,
        "user_reports_summary": "報告",
        "duration_s": 90.0,
    }
    _FakeClient.query_rows = [
        {**base, "resolution_recovered": True, "resolution_duration_s": 30.0},
        {**base, "pr_number": 8, "resolution_recovered": False, "resolution_duration_s": 60.0},
        {**base, "pr_number": None, "pr_url": None, "resolution_recovered": None,
         "resolution_duration_s": None},
    ]
    out = cs.recall_similar_cases("sida-target")
    if not (out["ok"] and out["enabled"] and out["count"] == 3):
        return False, f"out={out}"
    labels = [c["outcome"] for c in out["cases"]]
    ok = labels == ["verified_recovered", "recovery_failed", "unresolved_or_pending"]
    return ok, f"labels={labels}"


def test_recall_failure_degrades(cs):
    class _Boom(_FakeClient):
        def query(self, sql, job_config=None):
            raise RuntimeError("simulated query outage")

    sys.modules["google.cloud.bigquery"].Client = _Boom
    out = cs.recall_similar_cases("sida-target")
    sys.modules["google.cloud.bigquery"].Client = _FakeClient
    ok = out["ok"] is False and out["cases"] == [] and "error" in out
    return ok, f"out={out}"


def main() -> int:
    _install_fake_bigquery()
    os.environ.pop("AUTOSRE_CASES_TABLE", None)
    from agents import case_store as cs

    tests = [
        test_disabled_is_noop,
        test_record_diagnosis_row,
        test_skips_unparseable_diagnosis,
        test_record_resolution_row,
        test_insert_failure_never_raises,
        test_recall_outcome_labels,
        test_recall_failure_degrades,
    ]
    passed = 0
    for t in tests:
        try:
            ok, detail = t(cs)
            ok = bool(ok)  # tests may return the tail of an and-chain (truthy, not bool)
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"EXCEPTION {type(e).__name__}: {e}"
        print(("PASS" if ok else "FAIL"), t.__name__, "" if ok else f"-> {detail}")
        passed += 1 if ok else 0
    print(f"{passed}/{len(tests)} pass")
    return 0 if passed == len(tests) else 1


if __name__ == "__main__":
    sys.exit(main())
