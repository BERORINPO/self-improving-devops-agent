# AutoSRE — an autonomous on-call SRE agent

> **DevOps × AI Agent Hackathon 2026** submission (hosted by Findy, sponsored by Google Cloud).

When a deploy breaks at 2am, someone has to read the logs, find the cause, write the
fix, ship it — and verify it actually recovered. Solo founders and small teams don't
have an on-call SRE for that. **AutoSRE is an AI agent that runs the on-call
investigate-and-repair loop autonomously, and stops for your approval before it
changes anything.**

**Live demo:** https://sida-agent-860561433627.asia-northeast1.run.app

---

## What it does — five steps, and each one is the product

| Step | What the agent does | Why a single LLM call can't |
|------|---------------------|-----------------------------|
| **Sense** | Probes the target's health, tails **real Cloud Logging**, reads the **deployed Cloud Run config** | Multi-step tool use where each result decides the next action (a ReAct loop) |
| **Diagnose** | Gemini reasons over the real evidence and pinpoints the root cause | Grounded in the actual stack trace + config, not a plausible guess |
| **Propose** | Generates a concrete config fix | — |
| **Gate** | **Pauses for human approval** — the trust boundary | Suspends multi-source state across an unbounded human decision |
| **Verify** | After the fix is applied, polls health until it's green again | observe → act → observe closure — agency, not generation |

The line AutoSRE draws: **read / diagnose / propose = autonomous. Merge + deploy =
always human-approved.**

Every run produces a **real, permanent artifact**: the pull request the agent opened.
See a live example: https://github.com/BERORINPO/sida-target-config/pull/2

---

## Architecture

```
   Browser (Incident console, served by agent-service)
        │  POST /incident          POST /approve (human-gated)
        ▼
┌──────────────────────────────────────────────┐
│  agent-service  (Cloud Run, FastAPI + ADK)    │
│  ADK LlmAgent (Gemini 2.5 Flash) ReAct loop   │
│  tools: probe_health, get_recent_logs,        │
│         get_service_config, get_service_status│
│         open_pull_request                     │
└───┬─────────────┬──────────────┬──────────────┘
    │ read logs   │ read/patch   │ open + merge PR
    ▼             ▼              ▼
Cloud Logging   Cloud Run    GitHub (config repo)
                  API              │
                    │              │ on approval: merge
                    ▼              ▼
        ┌───────────────────────────────┐
        │  target-service (Cloud Run)   │  ← the "production" app under incident
        │  /health 503 without config   │
        └───────────────────────────────┘
```

## Tech stack (satisfies both required categories)

- **Google Cloud AI**: **Vertex AI Gemini 2.5 Flash**, driven by the **Google Agent
  Development Kit (ADK, `google-adk>=1.34,<2`)** as a single tool-using ReAct agent.
- **Google Cloud products**: **Cloud Run** (agent-service + target-service),
  **Cloud Logging** (grounded evidence), **Secret Manager** (GitHub token).
- **Backend**: Python 3.12 + FastAPI. **Frontend**: a single self-contained console
  page served by the agent-service (same-origin, no separate deploy).

## Repository layout

```
packages/agent/
  src/agents/
    server.py        FastAPI app: / (console), /incident, /approve, /target-health, /health, /smoke
    agent.py         ADK ReAct agent (build_agent, run_incident)
    tools.py         read-only investigation tools (Cloud Run + Logging + health probe)
    github_tools.py  open_pull_request (autonomous)
    recovery.py      merge + apply env fix + verify recovery (human-gated)
    static/index.html  the Incident console UI
  Dockerfile         Cloud Run container (uvicorn)
services/target-service/   the demo "production" app that breaks without DATABASE_URL
scripts/
  target-incident.ps1      inject / restore the demo incident
  test_agent_local.py      local end-to-end validation (no Cloud Build)
  test_recovery_local.py   local recovery validation
docs/sprint-4day-autosre.md  the plan + engineering log
```

## Run the demo

```powershell
# 1. break the target (removes DATABASE_URL -> /health 503)
pwsh scripts/target-incident.ps1 -Action inject

# 2. open the console and click "Run AutoSRE", then "Approve & deploy fix"
#    https://sida-agent-860561433627.asia-northeast1.run.app
```

The agent investigates the live service, opens a real fix PR, waits for your approval,
then merges + redeploys the target and confirms `/health` is back to 200.

## Deploy from scratch

See [docs/sprint-4day-autosre.md](docs/sprint-4day-autosre.md) for the full, reproducible
`gcloud run deploy` commands and the Cloud Run gotchas we hit (reserved `/healthz`,
PowerShell env-var quoting, Vertex `global` location).

## Roadmap (designed for, deliberately out of hackathon scope)

These were scoped out to ship one deep, reliable vertical slice in the hackathon window,
but the architecture is built for them:

- **Multi-Agent Debate** — 3 candidate fixes + a meta-selector, for ambiguous incidents.
- **Self-Improving autonomy policy** — learn autonomy thresholds from past-incident success rates (with statistical guards + shadow mode).
- **Auto-detection** — Cloud Monitoring + Pub/Sub to trigger AutoSRE without a manual click.
- **Incident history** — Firestore-backed audit trail and dedupe.
- **One-click deploy** — Terraform for the whole stack.
- **More scenarios** — 5xx spikes, memory leaks, dependency CVEs.

## License

Apache 2.0 — see [LICENSE](LICENSE).
