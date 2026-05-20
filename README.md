# Self-Improving Safe Autonomous DevOps Agent

> AI Agent Hackathon 2026 submission (DevOps x AI Agent Hackathon, hosted by Findy and Google Cloud).

## Tagline

**Self-Improving Safe Autonomous Agent** — an agent that learns from past incidents and proposes its own autonomy boundaries.

## Three Pillars

1. **Safe** — Approval Gate plus Autonomy Policy (three presets plus custom). Read / think / propose is autonomous; write / deploy requires human approval.
2. **Autonomous** — Multi-Agent Debate (three repair plans generated in parallel, then meta agent scores and selects).
3. **Self-Improving** — analyzes past incident success rates and proposes Autonomy Policy preset improvements. All proposals require human approval; statistical guards (n >= 30, 95% Wilson CI lower bound) and a shadow-mode kill switch are enforced.

## Worldview

Personal AI CEO Agent. Reference tenant: BeroBeroCompany. `config.yaml` generalizes to other tenants. Apache 2.0 from day one.

## Repository Layout (planned)

```
packages/
  agent/                ADK Python multi-agent orchestration (this MVP target)
apps/
  ops-console/          Next.js 16 + shadcn/ui Operations Console (W2+)
infra/
  terraform/            IaC for Cloud Run, Pub/Sub, Firestore, IAM
  cloudbuild.yaml       Cloud Build pipeline
.github/workflows/      GitHub Actions (lint / test / typecheck)
docs/                   Design docs (multi-agent-debate, self-improving-policy)
scripts/                Smoke tests, dev helpers
```

## Tech Stack (W1 confirmed)

- **Backend**: Python 3.12.x, Google ADK `>=1.34.0,<2.0.0` (v2.0 Beta intentionally excluded)
- **LLM**: Gemini 2.5 Pro (meta agent) + Gemini 2.5 Flash (workers)
- **Runtime**: Cloud Run Service (Orchestrator, Worker) + Cloud Run Job (Policy Improver, monthly)
- **Frontend**: Next.js 16 + shadcn/ui + Tailwind v4 + motion (Framer Motion successor)
- **State**: Firestore | **Queue**: Pub/Sub | **Schedule**: Cloud Scheduler
- **IaC**: Terraform + Cloud Run service.yaml
- **CI/CD**: GitHub Actions + Cloud Build

See [docs/](docs/) (W2+) for detailed design.

## License

Apache 2.0 — see [LICENSE](LICENSE).
