# Self-improving loop — case memory (BigQuery)

The repository name promises a *self-improving* DevOps agent. This document
describes the loop that delivers it: **every diagnosed incident becomes a case
in BigQuery, and the agent consults its own past cases at the start of the next
investigation.** The more incidents AutoSRE handles, the better grounded its
next diagnosis is.

```
incident ──▶ diagnose ──▶ propose PR ──▶ [human approves] ──▶ recover ──▶ verify 503→200
   ▲             │                                                        │
   │             ▼                                                        ▼
   │       cases (diagnosis row)                              cases (resolution row,
   │             BigQuery `autosre_memory.cases`               joined by pr_number)
   │             │
   └── next incident: recall_similar_cases ◀──────────────────┘
       (past cases = hypotheses, verified against live evidence)
```

## Design decisions

**Memory accelerates, evidence decides.** The recalled cases are injected as
*hypotheses*, never as proof. The agent instruction requires the same live
evidence (logs naming the variable, config showing it absent) before any
conclusion — a remembered root cause can never open a PR by itself. This keeps
the grounding discipline intact while repeat incidents converge faster.

**The resolution row is the teacher.** A diagnosis alone is a guess that looked
plausible; a diagnosis whose fix a human approved *and* whose 503→200
verification then succeeded is a confirmed playbook entry. The two are joined
by `pr_number`, and recall labels each past case `verified_recovered` /
`recovery_failed` / `unresolved_or_pending` so the model can weigh them
accordingly.

**Why BigQuery, not an app-local store.** AutoSRE already emits structured
logs; keeping case memory in BigQuery moves the model to where operational data
lives — SQL-queryable, joinable with Log Analytics, zero serving
infrastructure, and comfortably inside the free tier at demo scale. Access is
scoped: the runtime SA gets `dataEditor` on this one dataset plus project-level
`jobUser`, nothing wider.

**Default-off, like every AUTOSRE_* capability.** `AUTOSRE_CASES_TABLE` unset
means recording is a no-op and the recall tool reports `enabled=false`; a
memory outage degrades to exactly the pre-memory behavior (log + metric, never
an exception into the incident run). Deploys never break.

## Touch points

| where | what |
|---|---|
| `packages/agent/src/agents/case_store.py` | record + recall implementation (the only module that talks to BigQuery) |
| `agents/agent.py` | `recall_similar_cases` registered as step 2 of the investigation; hypothesis-not-proof grounding rule |
| `agents/server.py` | records a diagnosis case on all three run paths (manual / console / Pub/Sub); records the resolution outcome after `/approve` verification |
| `agents/static/index.html` | 「過去の類似インシデント」card — shows what the agent recalled, live |
| `terraform/bigquery.tf` | dataset + partitioned `cases` table + dataset-scoped IAM |
| `scripts/test_case_store_local.py` | offline smoke (7 cases): default-off, row shapes, outcome labels, never-raises |
