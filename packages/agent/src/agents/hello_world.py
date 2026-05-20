"""Hello-world ADK Sequential + Parallel Fan-Out/Gather pattern.

Mirrors the structure confirmed in `research/hackathon-tech-survey.md` (Topic 5,
"ADK Multi-Agent orchestration"). Three worker LlmAgents run in parallel and
write to distinct `output_key`s; the meta agent consumes them via
`{plan_a?}..{plan_c?}` template substitution.

W1 dry-run scope: import + agent construction only. Live LLM calls require
Vertex AI enabled and Application Default Credentials, which are part of W1-D
(GCP project + Vertex AI quota), handled in a later session.
"""

from google.adk.agents import LlmAgent, ParallelAgent, SequentialAgent


def build_root_agent() -> SequentialAgent:
    """Build the Multi-Agent Debate root agent.

    Returns a SequentialAgent that fans out to three worker LlmAgents in
    parallel, then runs a meta LlmAgent that scores and selects one plan.
    """
    worker_a = LlmAgent(
        name="worker_env_direct",
        model="gemini-2.5-flash",
        instruction=(
            "Return a JSON repair plan for an env-var outage. "
            "Approach: add env var directly in service.yaml."
        ),
        output_key="plan_a",
    )
    worker_b = LlmAgent(
        name="worker_secret_manager",
        model="gemini-2.5-flash",
        instruction=(
            "Return a JSON repair plan for an env-var outage. "
            "Approach: change to Secret Manager reference."
        ),
        output_key="plan_b",
    )
    worker_c = LlmAgent(
        name="worker_default_value",
        model="gemini-2.5-flash",
        instruction=(
            "Return a JSON repair plan for an env-var outage. "
            "Approach: add a default value in code."
        ),
        output_key="plan_c",
    )

    meta = LlmAgent(
        name="meta_selector",
        model="gemini-2.5-pro",
        instruction=(
            "Score the three repair plans by confidence / risk / cost, "
            "then pick the best and explain why. Output valid JSON only.\n\n"
            "Plan A: {plan_a?}\n"
            "Plan B: {plan_b?}\n"
            "Plan C: {plan_c?}\n"
        ),
        output_key="meta_decision",
    )

    return SequentialAgent(
        name="multi_agent_debate_root",
        sub_agents=[
            ParallelAgent(name="fan_out", sub_agents=[worker_a, worker_b, worker_c]),
            meta,
        ],
    )


def main() -> None:
    root = build_root_agent()
    print(f"Built root agent: {root.name}")
    fan_out = root.sub_agents[0]
    print(f"  Stage 1 (parallel): {fan_out.name}")
    for sub in fan_out.sub_agents:
        print(f"    - {sub.name}  model={sub.model}  output_key={sub.output_key}")
    meta = root.sub_agents[1]
    print(f"  Stage 2 (meta):     {meta.name}  model={meta.model}")
    print("OK: agent graph constructed; no LLM call performed (W1 dry-run).")


if __name__ == "__main__":
    main()
