"""Local smoke test for the AutoSRE agent (no HTTP, no Cloud Build).

Runs the ReAct agent against the REAL deployed target service using local ADC.
Usage (from repo root, with the agent venv):
    python scripts/test_agent_local.py
"""
import asyncio
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "packages", "agent", "src")
)

os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "TRUE")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "bero-devops-agent")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
os.environ.setdefault("RUN_REGION", "asia-northeast1")

from agents.agent import run_incident  # noqa: E402

TARGET_HEALTH_URL = os.environ.get(
    "TARGET_HEALTH_URL",
    "https://sida-target-860561433627.asia-northeast1.run.app/health",
)

INCIDENT = f"""Incident: the Cloud Run service 'sida-target' is reported unhealthy.
Its health endpoint is {TARGET_HEALTH_URL}.
Investigate the service and diagnose the single root cause."""


async def main() -> None:
    result = await run_incident(INCIDENT)
    print("=== STEPS ===")
    for s in result["steps"]:
        print(s)
    print("\n=== FINAL DIAGNOSIS ===")
    print(result["final"])


if __name__ == "__main__":
    asyncio.run(main())
