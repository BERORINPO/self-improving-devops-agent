"""Run the eval harness in REAL mode (actual Gemini via Vertex, tools mocked).

This is the exact driver used to produce docs/eval/real-report-2026-07-10.md.
Freeze-safe: mock tools mean zero GCP/GitHub side effects; only Gemini is real.

Prereqs: pip install -r packages/agent/requirements.txt (google-adk), plus ADC
with Vertex AI access on the project below.

Usage (from the repo root):
  python scripts/run_real_eval.py smoke        # 1 scenario x off x 1 rep (plumbing check)
  python scripts/run_real_eval.py full [reps]  # 17 scenarios x 3 arms x reps (default 3)

Outputs eval-<mode>-<stamp>.json (raw, includes per-run scoring) and, in full
mode, eval-report-<stamp>.md (report.render) into the current directory.
"""
import json
import os
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "packages", "agent", "src"))

os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "TRUE")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "bero-devops-agent")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")

from eval import report  # noqa: E402
from eval.runner import real_agent_diagnose, run_eval  # noqa: E402
from eval.scenarios import SCENARIOS  # noqa: E402

mode = sys.argv[1] if len(sys.argv) > 1 else "smoke"
if mode == "smoke":
    scns, arms, reps = SCENARIOS[:1], ("off",), 1
else:
    reps = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    scns, arms = list(SCENARIOS), ("off", "on-correct", "on-poisoned")

total = len(scns) * len(arms) * reps
state = {"n": 0, "errors": 0}


def diag(scn, tools, arm):
    state["n"] += 1
    t = time.time()
    print(f"[{state['n']}/{total}] {scn.id} arm={arm} ...", flush=True)
    try:
        run = real_agent_diagnose(scn, tools, arm)
        print(f"    done in {time.time() - t:.1f}s, {len(run.get('steps', []))} steps", flush=True)
        return run
    except Exception as e:  # noqa: BLE001 - record and keep the matrix going
        state["errors"] += 1
        print(f"    ERROR: {e!r}", flush=True)
        return {"final_text": f"__RUN_ERROR__: {e!r}", "steps": [], "duration_s": time.time() - t}


t0 = time.time()
results = run_eval(diag, reps=reps, arms=arms, scenarios=scns)
elapsed = time.time() - t0

commit = "unknown"
try:
    commit = subprocess.run(
        ["git", "-C", REPO, "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
except Exception:
    pass

stamp = time.strftime("%Y%m%d-%H%M%S")
raw_path = f"eval-{mode}-{stamp}.json"
with open(raw_path, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=1, default=str)

print(f"\n=== elapsed {elapsed / 60:.1f} min, run errors {state['errors']}, raw -> {raw_path}", flush=True)

if mode == "smoke":
    print(json.dumps(results["_scored"]["off"], ensure_ascii=False, indent=1, default=str)[:3000], flush=True)
else:
    md = report.render(results, model=os.environ.get("AUTOSRE_MODEL", "gemini-2.5-flash"), commit=commit)
    md_path = f"eval-report-{stamp}.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"report -> {md_path}", flush=True)
    print(md, flush=True)
