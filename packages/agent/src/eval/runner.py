"""Runs each scenario through a diagnose function across memory arms + R repeats.

The diagnose function is injected so the harness is testable offline:
- REAL mode  : `real_agent_diagnose` runs the actual ADK agent with the mock
               tools monkeypatched over agents.agent's imported references, and
               scenario-scoped env (REQUIRED/ALLOWED/RESTORE/CASES_TABLE).
               Needs Gemini (+ google-adk); no GCP/GitHub (tools are mocked).
- STUB mode  : any callable returning {final_text, steps, duration_s}. Used by
               the offline unit test to exercise the runner without an LLM.

Freeze-safe: nothing here touches the live services, main, or prod config — the
mock path is zero-network, and even a real-agent mock run only calls Gemini.
"""
import time

from .judge import aggregate, score_run
from .mock_tools import build_mock_tools
from .scenarios import SCENARIOS, derive_gt

MEMORY_ARMS = ("off", "on-correct", "on-poisoned")


def real_agent_diagnose(scn, tools, memory_arm):  # pragma: no cover - needs Gemini+ADK
    """Run the real ADK agent with mock tools patched in. Returns {final_text, steps, duration_s}.

    Imported lazily so the offline test never needs google-adk installed.
    """
    import agents.agent as agent_mod
    from agents.agent import run_incident

    # Patch the tool references the agent imported (same technique as the smoke
    # tests' fake injection). Save + restore so runs don't leak into each other.
    saved = {}
    for name, fn in tools.items():
        if hasattr(agent_mod, name):
            saved[name] = getattr(agent_mod, name)
            setattr(agent_mod, name, fn)
    try:
        import asyncio

        incident_text = (
            f"Incident: the Cloud Run service 'sida-target' is reported unhealthy. "
            f"Its health endpoint is https://sida-target.example/health. "
            f"Investigate and diagnose the single root cause."
        )
        started = time.time()
        result = asyncio.get_event_loop().run_until_complete(run_incident(incident_text))
        return {
            "final_text": result["final"],
            "steps": result["steps"],
            "duration_s": time.time() - started,
        }
    finally:
        for name, fn in saved.items():
            setattr(agent_mod, name, fn)


def run_eval(diagnose, reps: int = 5, arms=MEMORY_ARMS, scenarios=SCENARIOS) -> dict:
    """Run the full matrix (scenario x arm x reps) and aggregate per arm.

    `diagnose(scenario, tools, memory_arm) -> {final_text, steps, duration_s}`.
    """
    per_arm = {}
    for arm in arms:
        scored = []
        for scn in scenarios:
            gt = derive_gt(scn)
            tools = build_mock_tools(scn, memory_arm=arm)
            for _ in range(reps):
                run = diagnose(scn, tools, arm)
                scored.append(score_run(scn, gt, run))
        per_arm[arm] = {"aggregate": aggregate(scored), "scored": scored}
    return {
        "reps": reps,
        "scenarios": len(scenarios),
        "arms": {arm: per_arm[arm]["aggregate"] for arm in arms},
        "memory_gain": _memory_gain(per_arm),
        "_scored": {arm: per_arm[arm]["scored"] for arm in arms},
    }


def _median(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2


def _memory_gain(per_arm: dict) -> dict:
    """Memory claim = speed only; accuracy must be UNCHANGED (a rise = leak = RED)."""
    if "off" not in per_arm or "on-correct" not in per_arm:
        return {}
    off = per_arm["off"]["aggregate"]
    on = per_arm["on-correct"]["aggregate"]
    off_acc = off["diagnosis_accuracy"]["rate"]
    on_acc = on["diagnosis_accuracy"]["rate"]
    off_tc = _median([s["tool_calls"] for s in per_arm["off"]["scored"]])
    on_tc = _median([s["tool_calls"] for s in per_arm["on-correct"]["scored"]])
    tool_reduction = None
    if off_tc:
        tool_reduction = (off_tc - on_tc) / off_tc
    poisoned_acc = (
        per_arm.get("on-poisoned", {}).get("aggregate", {})
        .get("diagnosis_accuracy", {})
        .get("rate")
    )
    return {
        "accuracy_delta_pp": round((on_acc - off_acc) * 100, 2),  # requirement: ~0
        "accuracy_leak": (on_acc - off_acc) > 0.001,  # RED if memory raised accuracy
        "tool_call_reduction": tool_reduction,        # the honest, claimable gain
        "poisoned_accuracy": poisoned_acc,            # must not degrade vs off
        "poisoned_degraded": (
            poisoned_acc is not None and poisoned_acc < off_acc - 0.001
        ),
        "ungrounded_correct_total": sum(
            a["ungrounded_correct"] for a in (off, on) if "ungrounded_correct" in a
        ),
    }
