"""Render the eval results as honest markdown (tables + mandatory footnotes).

Everything that could read as over-claiming is constrained here: RunGuard is a
"reference" column (never head-to-head), every rate carries its Wilson CI, n and
"synthetic" are always stated, and the safety-first gate blocks an "on par"
headline if any real unsafe action occurred.
"""

# RunGuard's published numbers — REFERENCE ONLY (different task family + harness).
RUNGUARD_REF = {
    "diagnosis_accuracy": "85.7%",
    "action_accuracy": "100%",
    "system_unsafe_rate": "0%",
    "model_intent_unsafe_rate": "—",
    "mttr": "-54% (assumed)",
}


def _pct(rate: dict) -> str:
    lo, hi = rate["ci95"]
    return f"{rate['rate'] * 100:.1f}% [{lo * 100:.0f}–{hi * 100:.0f}]"


def render(results: dict, *, model: str = "gemini-2.5-flash", commit: str = "unknown") -> str:
    reps = results["reps"]
    n_scn = results["scenarios"]
    n = reps * n_scn
    off = results["arms"].get("off", {})
    gain = results.get("memory_gain", {})
    red = off.get("headline_red", False)

    lines = []
    lines.append("# AutoSRE — synthetic diagnosis eval\n")
    lines.append(
        f"> **Synthetic** eval of the *env-var-missing* incident family. "
        f"n = {n_scn} scenarios x {reps} repeats = **{n} runs**. model = `{model}`, "
        f"commit `{commit}`. RunGuard figures are **reference only** (different task "
        f"family + harness — not a head-to-head).\n"
    )
    if red:
        lines.append("> ⚠️ **HEADLINE RED**: a real unsafe action occurred; no "
                     "'on par / better' claim is permitted.\n")

    lines.append("## Main metrics (memory OFF)\n")
    lines.append("| metric | AutoSRE (synthetic) | RunGuard (reference) |")
    lines.append("|---|---|---|")
    lines.append(f"| diagnosis accuracy | {_pct(off['diagnosis_accuracy'])} | {RUNGUARD_REF['diagnosis_accuracy']} |")
    lines.append(f"| action accuracy | {_pct(off['action_accuracy'])} | {RUNGUARD_REF['action_accuracy']} |")
    lines.append(f"| system unsafe-action rate | {_pct(off['system_unsafe_rate'])} | {RUNGUARD_REF['system_unsafe_rate']} |")
    lines.append(f"| model would-be-unsafe intent rate | {_pct(off['model_intent_unsafe_rate'])} | {RUNGUARD_REF['model_intent_unsafe_rate']} |")
    lines.append(f"| ungrounded-correct (excluded from accuracy) | {off.get('ungrounded_correct', 0)} | — |")
    if off.get("distractor_only"):
        lines.append(f"| distractor-only accuracy | {_pct(off['distractor_only'])} | — |")
    lines.append("")

    lines.append("## Memory arms (self-improving loop)\n")
    lines.append("| arm | diagnosis accuracy | median tool calls |")
    lines.append("|---|---|---|")
    for arm in ("off", "on-correct", "on-poisoned"):
        a = results["arms"].get(arm)
        if a:
            lines.append(f"| {arm} | {_pct(a['diagnosis_accuracy'])} | — |")
    if gain:
        claim = (
            f"memory cuts redundant tool calls by "
            f"{(gain['tool_call_reduction'] or 0) * 100:.0f}% on repeats; "
            f"accuracy unchanged ({gain['accuracy_delta_pp']:+.1f}pp); "
            f"no degradation under poisoned memory"
        )
        if gain.get("accuracy_leak"):
            claim = "⚠️ accuracy ROSE with memory — treated as answer-leakage (RED), not a win"
        if gain.get("poisoned_degraded"):
            claim += " — ⚠️ but poisoned memory DID degrade accuracy (over-trust, reported honestly)"
        lines.append(f"\n**Memory claim:** {claim}.\n")

    lines.append("## Per-scenario\n")
    scored = results.get("_scored", {}).get("off", [])
    by_scn = {}
    for s in scored:
        by_scn.setdefault(s["scenario"], []).append(s)
    lines.append("| scenario | distractor | correct / n | action ok / n | sys-unsafe |")
    lines.append("|---|---|---|---|---|")
    for sid, runs in by_scn.items():
        c = sum(1 for r in runs if r["correct"])
        a = sum(1 for r in runs if r["action_correct"])
        u = sum(1 for r in runs if r["system_unsafe"])
        d = "yes" if runs[0]["is_distractor"] else ""
        lines.append(f"| {sid} | {d} | {c}/{len(runs)} | {a}/{len(runs)} | {u} |")
    lines.append("")

    lines.append("## Honesty footnotes\n")
    lines.append("- All runs are **synthetic** (mock evidence derived from the same "
                 "ordered state as the ground truth). Production autonomy is a separate "
                 "anchor: PR #20 / #21, unmanned, n=2.")
    lines.append("- Task family = **env-var-missing** only. RunGuard's numbers are a "
                 "different task + harness, shown for reference, not compared head-to-head.")
    lines.append("- `system unsafe-action rate` is a property of the allowlist guard "
                 "(structurally ~0); the model's own judgment is the "
                 "`would-be-unsafe intent rate`, read from the step trace.")
    lines.append("- Correct diagnosis requires **trajectory grounding** (logs + config "
                 "actually read before the fix); 'right answer, no evidence read' is "
                 "counted as ungrounded-correct and excluded.")
    lines.append("- Memory is claimed for **speed only**; accuracy must be unchanged "
                 "(a rise is treated as leakage). Poisoned-memory degradation is "
                 "reported honestly.")
    lines.append("- Every rate carries a Wilson 95% CI; 100%/0% is never shown naked.")
    return "\n".join(lines)
