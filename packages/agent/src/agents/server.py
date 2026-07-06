"""AutoSRE agent-service (Cloud Run, FastAPI + ADK).

Day 1 smoke gate: prove that Vertex Gemini + Cloud Logging both work from the
Cloud Run runtime service account. Day 2 adds /incident (the ReAct investigate ->
diagnose -> propose -> open-PR loop) and /events (SSE stream).

Env contract (set via `gcloud run deploy --set-env-vars`):
  GOOGLE_GENAI_USE_VERTEXAI=TRUE
  GOOGLE_CLOUD_PROJECT=<project id>
  GOOGLE_CLOUD_LOCATION=<vertex location, e.g. global or us-central1>
"""
import os

from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="AutoSRE agent-service")

GEMINI_MODEL = "gemini-2.5-flash"


# NOTE: "/healthz" is a reserved path intercepted by the Cloud Run front end
# (GFE returns its own 404 before the request reaches the container), so we
# expose the health check at "/health" instead.
@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/")
def root() -> dict:
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
