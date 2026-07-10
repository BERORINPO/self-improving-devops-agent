"""Offline unit smoke for agent._summarize_result (pure function, no cloud).

Covers: per-tool bounded summaries, ERROR-line extraction from logs (including
malformed entries), non-dict input, unknown tools, and the never-raises contract.

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
check("logs_first_error_extraction", s is not None and s["count"] == 3
      and s["first_error"] == "" or (s and len(s["first_error"] or "") <= 160), str(s))
# 最初の ERROR は text=None -> 空文字に落ちる (TypeError にならない) こと自体が契約
check("logs_malformed_entries_never_raise", s is not None and s.get("ok") is True, str(s))

s = _summarize_result("get_recent_logs", {"ok": True, "count": 1, "entries": [
    {"severity": "ERROR", "text": "startup check failed: DATABASE_URL is not set"}]})
check("logs_error_text", s["first_error"] == "startup check failed: DATABASE_URL is not set", str(s))

s = _summarize_result("get_service_config",
                      {"ok": True, "env_var_names": ["A", "B", "C"], "env_vars": {"A": "secret!"}})
check("config_counts_only_no_values", s == {"ok": True, "env_count": 3}, str(s))

s = _summarize_result("open_pull_request",
                      {"ok": True, "pr_number": 29, "pr_url": "https://github.com/x/y/pull/29"})
check("pr_summary", s == {"ok": True, "pr_number": 29,
                          "pr_url": "https://github.com/x/y/pull/29"}, str(s))

check("recall_summary", _summarize_result("recall_similar_cases",
      {"enabled": True, "count": 2, "cases": [{}, {}]}) == {"enabled": True, "count": 2})

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
