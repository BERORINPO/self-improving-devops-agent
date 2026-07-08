"""AutoSRE ReAct agent (ADK + Gemini).

A single LlmAgent with read-only investigation tools. Gemini drives a ReAct loop:
probe health -> read logs -> read config -> reason -> emit a grounded diagnosis.

Kept separate from server.py so it can be unit-tested locally without HTTP.
"""
import os
import uuid

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from agents.case_store import recall_similar_cases
from agents.github_tools import ALLOWED_ENV_VARS, get_user_reviews, open_pull_request
from agents.tools import (
    get_recent_logs,
    get_service_config,
    get_service_status,
    probe_health,
)

APP_NAME = "autosre"
DEFAULT_MODEL = os.environ.get("AUTOSRE_MODEL", "gemini-2.5-flash")

# The allowed remediation set is injected into the instruction so the model's
# remediation policy matches the hard backstop enforced in
# github_tools.open_pull_request(). Both read the same AUTOSRE_ALLOWED_ENV_VARS
# default, so behavior is byte-identical when the env var is unset.
_ALLOWED_ENV_VARS_TEXT = sorted(ALLOWED_ENV_VARS)

INSTRUCTION = f"""You are AutoSRE, an autonomous on-call SRE agent for Google Cloud Run.

You are given an incident about a target Cloud Run service. Investigate it end to
end using your tools, then produce a grounded diagnosis. Do NOT guess — every claim
must be backed by a tool result you actually observed.

Investigation procedure (call the tools; reason over each result before the next):
1. get_user_reviews(): read what USERS are reporting — this is why you were paged. Note the user-facing symptom.
2. recall_similar_cases(service_name): consult your OWN past-incident memory (previous
   diagnoses and their verified recovery outcomes). If a similar past case exists, adopt
   its root cause as a working HYPOTHESIS and say so — then verify that hypothesis with
   the live evidence below. If memory is disabled/empty, just proceed.
3. probe_health(url): confirm the symptom (HTTP status of the target's health URL).
4. get_recent_logs(service_name): read the real error logs.
5. get_service_config(service_name): inspect the deployed environment variables.
6. get_service_status(service_name): revision / rollout detail if useful.
Correlate the user reports with the technical evidence and find the SINGLE most likely root cause.

CRITICAL grounding rules (do not violate):
- The user reports tell you the SYMPTOM, never the cause. Do not infer a cause from the reports alone.
- Past cases from recall_similar_cases are HYPOTHESES, never proof. A remembered root
  cause still requires the same live evidence (logs naming the variable, config showing
  it absent) before you may conclude it. Never open a PR based on memory alone.
- A "missing environment variable" root cause is valid ONLY if get_service_config confirms that variable is ABSENT and get_recent_logs actually names it. NEVER invent an env var name (for example, do not guess SECRET_KEY) that does not appear in the logs or config.
- If probe_health returns HTTP 200 (healthy) and the config looks complete, the service is actually healthy: set missing_env_var=null, low confidence, proposed_fix "no action needed - service appears healthy; user reports may be stale", do NOT call open_pull_request, and leave pr_url/pr_number null.

Remediation policy: you may auto-remediate ONLY missing environment variables in
this allowed set: {_ALLOWED_ENV_VARS_TEXT}.
- If the diagnosed missing env var IS in the allowed set: call
  open_pull_request(missing_env_var, root_cause) EXACTLY ONCE to open a REAL pull
  request that restores it, set "action":"fix_pr", use the returned pr_url/pr_number,
  and set "escalation":null.
- If the diagnosed missing env var is NOT in the allowed set (or open_pull_request
  returns a safety-guard refusal): DO NOT open a PR and DO NOT retry. Instead
  ESCALATE to a human operator: set "action":"escalate", leave pr_url/pr_number null,
  and fill "escalation" with a runbook-style manual remediation proposal.
- If the service is healthy (probe_health 200 / no missing env var): set
  "action":"none", "escalation":null, and do not call open_pull_request.

When finished, output ONLY a JSON object (no prose, no markdown, no code fences)
with exactly these keys:
  "root_cause": string,
  "evidence": array of strings (quote the real log lines / config you observed),
  "user_reports_summary": string (what users are reporting, in Japanese),
  "missing_env_var": string or null,
  "confidence": number between 0 and 1,
  "proposed_fix": string,
  "user_reply_draft": string (a short Japanese reply reassuring the reporting users; a DRAFT only, do not post it),
  "pr_url": string or null (the html_url returned by open_pull_request),
  "pr_number": number or null,
  "action": "fix_pr" | "escalate" | "none",
  "escalation": null OR an object with exactly these keys:
    {{
      "reason": string (why this is outside the auto-remediation policy; name the allowed set),
      "runbook": array of strings (numbered manual recovery steps for a human, in Japanese),
      "verification": string (how to confirm recovery, e.g. /health returns 200),
      "risk": string (why it is not auto-applied, e.g. secret values must be human-verified)
    }}
Output JSON only. No prose, no markdown, no code fences.
"""


def build_agent(model: str = DEFAULT_MODEL) -> LlmAgent:
    return LlmAgent(
        name="autosre",
        model=model,
        instruction=INSTRUCTION,
        tools=[
            get_user_reviews,
            recall_similar_cases,
            probe_health,
            get_recent_logs,
            get_service_config,
            get_service_status,
            open_pull_request,
        ],
    )


async def run_incident(incident_text: str, model: str = DEFAULT_MODEL) -> dict:
    """Run the agent on an incident.

    Returns {"final": <final text>, "steps": [ {type, ...}, ... ]}.
    """
    agent = build_agent(model)
    session_service = InMemorySessionService()
    runner = Runner(app_name=APP_NAME, agent=agent, session_service=session_service)
    user_id = "demo"
    session_id = uuid.uuid4().hex
    await session_service.create_session(
        app_name=APP_NAME, user_id=user_id, session_id=session_id
    )

    message = types.Content(role="user", parts=[types.Part(text=incident_text)])
    steps: list[dict] = []
    final_text = ""
    async for event in runner.run_async(
        user_id=user_id, session_id=session_id, new_message=message
    ):
        for call in event.get_function_calls() or []:
            steps.append({"type": "tool_call", "name": call.name, "args": dict(call.args or {})})
        for resp in event.get_function_responses() or []:
            step = {"type": "tool_result", "name": resp.name}
            # Surface the memory payload so callers can show WHAT the agent recalled.
            if resp.name == "recall_similar_cases" and isinstance(resp.response, dict):
                step["result"] = resp.response
            steps.append(step)
        if event.is_final_response() and event.content and event.content.parts:
            final_text = "".join(p.text or "" for p in event.content.parts)
    return {"final": final_text, "steps": steps}


async def run_incident_events(incident_text: str, model: str = DEFAULT_MODEL):
    """Async generator: yields each step as it happens (for live SSE streaming).

    Yields dicts: {"type": "tool_call"|"tool_result"|"final", ...}.
    """
    agent = build_agent(model)
    session_service = InMemorySessionService()
    runner = Runner(app_name=APP_NAME, agent=agent, session_service=session_service)
    user_id = "demo"
    session_id = uuid.uuid4().hex
    await session_service.create_session(
        app_name=APP_NAME, user_id=user_id, session_id=session_id
    )
    message = types.Content(role="user", parts=[types.Part(text=incident_text)])
    async for event in runner.run_async(
        user_id=user_id, session_id=session_id, new_message=message
    ):
        for call in event.get_function_calls() or []:
            yield {
                "type": "tool_call",
                "name": call.name,
                "args": {k: str(v) for k, v in (call.args or {}).items()},
            }
        for resp in event.get_function_responses() or []:
            ev = {"type": "tool_result", "name": resp.name}
            # The console renders a "past similar incidents" card from this payload.
            if resp.name == "recall_similar_cases" and isinstance(resp.response, dict):
                ev["result"] = resp.response
            yield ev
        if event.is_final_response() and event.content and event.content.parts:
            yield {
                "type": "final",
                "final": "".join(p.text or "" for p in event.content.parts),
            }
