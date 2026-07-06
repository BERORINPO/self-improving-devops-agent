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

from agents.github_tools import open_pull_request
from agents.tools import (
    get_recent_logs,
    get_service_config,
    get_service_status,
    probe_health,
)

APP_NAME = "autosre"
DEFAULT_MODEL = os.environ.get("AUTOSRE_MODEL", "gemini-2.5-flash")

INSTRUCTION = """You are AutoSRE, an autonomous on-call SRE agent for Google Cloud Run.

You are given an incident about a target Cloud Run service. Investigate it end to
end using your tools, then produce a grounded diagnosis. Do NOT guess — every claim
must be backed by a tool result you actually observed.

Investigation procedure (call the tools; reason over each result before the next):
1. probe_health(url): confirm the symptom (HTTP status of the target's health URL).
2. get_recent_logs(service_name): read the real error logs.
3. get_service_config(service_name): inspect the deployed environment variables.
4. get_service_status(service_name): revision / rollout detail if useful.
Cross-reference the evidence to find the SINGLE most likely root cause.

Once the root cause is a missing environment variable, call
open_pull_request(missing_env_var, root_cause) EXACTLY ONCE to open a REAL pull
request that restores it. Use the pr_url / pr_number it returns in your final output.

When finished, output ONLY a JSON object (no prose, no markdown, no code fences)
with exactly these keys:
  "root_cause": string,
  "evidence": array of strings (quote the real log lines / config you observed),
  "missing_env_var": string or null,
  "confidence": number between 0 and 1,
  "proposed_fix": string,
  "pr_url": string or null (the html_url returned by open_pull_request),
  "pr_number": number or null.
"""


def build_agent(model: str = DEFAULT_MODEL) -> LlmAgent:
    return LlmAgent(
        name="autosre",
        model=model,
        instruction=INSTRUCTION,
        tools=[
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
            steps.append({"type": "tool_result", "name": resp.name})
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
            yield {"type": "tool_result", "name": resp.name}
        if event.is_final_response() and event.content and event.content.parts:
            yield {
                "type": "final",
                "final": "".join(p.text or "" for p in event.content.parts),
            }
