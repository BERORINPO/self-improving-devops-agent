"""Offline unit smoke for agent._summarize_result (pure function, no cloud).

Covers: per-tool bounded summaries, raw-log omission (including malformed
entries), non-dict input, unknown tools, and the never-raises contract.

Run: PYTHONPATH=packages/agent/src python scripts/test_summarize_local.py
"""
import sys

from agents.agent import _summarize_result

PASSED = 0
FAILED = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"PASS {name}")
    else:
        FAILED += 1
        print(f"FAIL {name} {detail}")


s = _summarize_result("probe_health", {"ok": True, "status_code": 503, "healthy": False,
                                       "body": "x" * 5000, "url": "https://t/health"})
check("probe_health_bounded", s == {"ok": True, "status_code": 503, "healthy": False}, str(s))

s = _summarize_result("get_recent_logs", {"ok": True, "count": 3, "entries": [
    {"severity": "INFO", "text": "boot"},
    "malformed-entry",
    {"severity": "ERROR", "text": None},
    {"severity": "ERROR", "text": "E" * 500},
]})
check("logs_bounded_without_body", s == {"ok": True, "count": 3}, str(s))
check("logs_malformed_entries_never_raise", s is not None and s.get("ok") is True, str(s))

s = _summarize_result("get_recent_logs", {"ok": True, "count": 1, "entries": [
    {"severity": "ERROR", "text": "Authorization: Bearer super-secret-token"}]})
check("logs_secret_not_exposed", s == {"ok": True, "count": 1}
      and "super-secret-token" not in repr(s) and "first_error" not in s, str(s))

s = _summarize_result("get_service_config",
                      {"ok": True, "env_var_names": ["A", "B", "C"], "env_vars": {"A": "secret!"}})
check("config_counts_only_no_values", s == {"ok": True, "env_count": 3}, str(s))

s = _summarize_result("open_pull_request",
                      {"ok": True, "pr_number": 29, "pr_url": "https://github.com/x/y/pull/29"})
check("pr_summary", s == {"ok": True, "pr_number": 29,
                          "pr_url": "https://github.com/x/y/pull/29"}, str(s))

check("recall_summary", _summarize_result("recall_similar_cases",
      {"ok": True, "enabled": True, "count": 2, "cases": [{}, {}]})
      == {"enabled": True, "ok": True, "count": 2})
check("recall_outage_preserves_failure", _summarize_result("recall_similar_cases",
      {"ok": False, "enabled": True, "cases": [], "error": "backend down"})
      == {"enabled": True, "ok": False, "count": None})
check("recall_disabled_preserves_state", _summarize_result("recall_similar_cases",
      {"ok": True, "enabled": False, "cases": []})
      == {"enabled": False, "ok": True, "count": None})

s = _summarize_result("analyze_report_video",
                      {"enabled": True, "ok": True, "reproduction_steps": ["a", "b"],
                       "timeline": [{"t": "0:01"}]})
check("video_summary", s == {"enabled": True, "ok": True, "steps": 2, "timeline": 1}, str(s))

check("non_dict_input_none", _summarize_result("probe_health", "oops") is None)
check("unknown_tool_none", _summarize_result("mystery_tool", {"ok": True}) is None)
check("never_raises_on_weird_shapes",
      _summarize_result("get_recent_logs", {"entries": 123}) is None
      or True)  # 例外にならなければ良い (値は None or dict どちらも契約内)

print(f"{PASSED}/{PASSED + FAILED} pass")
sys.exit(0 if FAILED == 0 else 1)
