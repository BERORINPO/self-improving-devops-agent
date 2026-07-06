"""AutoSRE agent-service (Cloud Run, FastAPI + ADK).

Day 1 smoke gate: prove that Vertex Gemini + Cloud Logging both work from the
Cloud Run runtime service account. Day 2 adds /incident (the ReAct investigate ->
diagnose -> propose -> open-PR loop) and /events (SSE stream).

Env contract (set via `gcloud run deploy --set-env-vars`):
  GOOGLE_GENAI_USE_VERTEXAI=TRUE
  GOOGLE_CLOUD_PROJECT=<project id>
  GOOGLE_CLOUD_LOCATION=<vertex location, e.g. global or us-central1>
"""
import json
import os
import re
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

_UI_HTML = (Path(__file__).parent / "static" / "index.html").read_text(encoding="utf-8")

app = FastAPI(title="AutoSRE agent-service")

GEMINI_MODEL = "gemini-2.5-flash"


# NOTE: "/healthz" is a reserved path intercepted by the Cloud Run front end
# (GFE returns its own 404 before the request reaches the container), so we
# expose the health check at "/health" instead.
@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def ui() -> str:
    return _UI_HTML


@app.get("/target-health")
def target_health() -> dict:
    from agents.tools import probe_health

    return probe_health(os.environ.get("TARGET_HEALTH_URL", ""))


@app.get("/api/info")
def info() -> dict:
    return {
        "service": "autosre-agent",
        "project": os.environ.get("GOOGLE_CLOUD_PROJECT"),
        "location": os.environ.get("GOOGLE_CLOUD_LOCATION"),
        "use_vertex": os.environ.get("GOOGLE_GENAI_USE_VERTEXAI"),
    }


def _gemini_smoke() -> dict:
    """One real Gemini call via Vertex AI (uses the runtime SA / ADC)."""
    try:
        from google import genai

        project = os.environ["GOOGLE_CLOUD_PROJECT"]
        location = os.environ.get("GOOGLE_CLOUD_LOCATION", "global")
        client = genai.Client(vertexai=True, project=project, location=location)
        resp = client.models.generate_content(
            model=GEMINI_MODEL,
            contents="Reply with exactly this token and nothing else: SMOKE_OK",
        )
        return {"ok": True, "model": GEMINI_MODEL, "text": (resp.text or "").strip()}
    except Exception as e:  # noqa: BLE001 - surface the exact error to the smoke caller
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _logging_smoke() -> dict:
    """One real Cloud Logging read (proves logging.viewer + API from Cloud Run)."""
    try:
        from google.cloud import logging as gcloud_logging

        project = os.environ["GOOGLE_CLOUD_PROJECT"]
        client = gcloud_logging.Client(project=project)
        recent: list[str] = []
        for entry in client.list_entries(order_by=gcloud_logging.DESCENDING, page_size=5):
            payload = getattr(entry, "payload", None)
            recent.append(str(payload)[:160] if payload is not None else f"<{entry.severity}>")
            if len(recent) >= 3:
                break
        return {"ok": True, "count": len(recent), "recent": recent}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


@app.get("/smoke")
def smoke() -> JSONResponse:
    """Day-1 gate: one real Gemini call + one real Cloud Logging read from Cloud Run."""
    gemini = _gemini_smoke()
    logging_result = _logging_smoke()
    overall_ok = gemini["ok"] and logging_result["ok"]
    return JSONResponse(
        status_code=200 if overall_ok else 500,
        content={"overall_ok": overall_ok, "gemini": gemini, "logging": logging_result},
    )


def _parse_diagnosis(text: str) -> dict:
    """Tolerantly extract the agent's final JSON diagnosis (models sometimes wrap it in code fences)."""
    if not text:
        return {"error": "empty_final"}
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?", "", t).strip()
        t = re.sub(r"```$", "", t).strip()
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end > start:
        t = t[start : end + 1]
    try:
        return json.loads(t)
    except Exception as e:  # noqa: BLE001
        return {"error": f"parse_failed: {e}", "raw": text[:500]}


class IncidentRequest(BaseModel):
    service_name: str = "sida-target"
    target_health_url: str | None = None


@app.post("/incident")
async def incident(req: IncidentRequest) -> dict:
    """Run the AutoSRE agent on an incident: investigate -> diagnose -> open a real fix PR."""
    from agents.agent import run_incident  # lazy import (heavy ADK deps, keep startup fast)

    health_url = req.target_health_url or os.environ.get("TARGET_HEALTH_URL", "")
    incident_text = (
        f"Incident: the Cloud Run service '{req.service_name}' is reported unhealthy. "
        f"Its health endpoint is {health_url}. Investigate and diagnose the single root cause."
    )
    result = await run_incident(incident_text)
    return {
        "steps": result["steps"],
        "diagnosis": _parse_diagnosis(result["final"]),
        "raw_final": result["final"],
    }


class ApproveRequest(BaseModel):
    pr_number: int
    service_name: str = "sida-target"
    env_var: str = "DATABASE_URL"
    target_health_url: str | None = None


@app.post("/approve")
def approve(req: ApproveRequest) -> dict:
    """Human-gated recovery: merge the fix PR, apply the env fix, verify the target is healthy."""
    from agents.recovery import apply_env_fix, merge_pull_request, verify_recovery

    value = os.environ.get(f"AUTOSRE_RESTORE_{req.env_var}", "")
    merge = merge_pull_request(req.pr_number)
    applied = apply_env_fix(req.service_name, req.env_var, value)
    health_url = req.target_health_url or os.environ.get("TARGET_HEALTH_URL", "")
    verify = verify_recovery(health_url)
    return {"merge": merge, "apply": applied, "verify": verify}
