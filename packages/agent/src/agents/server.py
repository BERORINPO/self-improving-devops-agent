"""AutoSRE agent-service (Cloud Run, FastAPI + ADK).

Day 1 smoke gate: prove that Vertex Gemini + Cloud Logging both work from the
Cloud Run runtime service account. Day 2 adds /incident (the ReAct investigate ->
diagnose -> propose -> open-PR loop) and /incident/stream (per-connection SSE).

/events is a persistent, read-only SSE broadcast channel: any open console
subscribes on page load, and a Pub/Sub-triggered agent run on POST /pubsub/incident
is fanned out to every subscriber so a real Cloud Monitoring alert makes every open
console timeline come alive with no human click.

Env contract (set via `gcloud run deploy --set-env-vars`):
  GOOGLE_GENAI_USE_VERTEXAI=TRUE
  GOOGLE_CLOUD_PROJECT=<project id>
  GOOGLE_CLOUD_LOCATION=<vertex location, e.g. global or us-central1>
"""
import asyncio
import base64
import hmac
import json
import os
import re
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
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


def _classify_outcome(d: dict) -> str:
    """Classify the agent's diagnosis into a single outcome label (frozen cross-worker contract)."""
    if d.get("pr_url"):
        return "pr_opened"
    if d.get("action") == "escalate" or d.get("escalation"):
        return "escalated"
    if d.get("missing_env_var") is None:
        return "healthy"
    return "none"


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
    diagnosis = _parse_diagnosis(result["final"])
    return {
        "steps": result["steps"],
        "outcome": _classify_outcome(diagnosis),
        "diagnosis": diagnosis,
        "raw_final": result["final"],
    }


def _check_console_key(request: Request) -> None:
    """Gate on AUTOSRE_CONSOLE_KEY (default-off). Accept Bearer header OR ?key= query param."""
    expected = os.environ.get("AUTOSRE_CONSOLE_KEY", "")
    if not expected:
        return  # unset -> open = current behavior
    supplied = (
        request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        or request.query_params.get("key", "")
    )
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="console key required")


class ApproveRequest(BaseModel):
    pr_number: int
    service_name: str = "sida-target"
    env_var: str = "DATABASE_URL"
    target_health_url: str | None = None


@app.post("/approve")
def approve(req: ApproveRequest, request: Request) -> dict:
    """Human-gated recovery: merge the fix PR, apply the env fix, verify the target is healthy."""
    _check_console_key(request)
    from agents.github_tools import ALLOWED_ENV_VARS
    from agents.recovery import apply_env_fix, merge_pull_request, verify_recovery

    if req.env_var not in ALLOWED_ENV_VARS:
        return {
            "ok": False,
            "error": f"'{req.env_var}' is not in the allowed remediation set; escalated vars require manual operation",
        }
    value = os.environ.get(f"AUTOSRE_RESTORE_{req.env_var}", "")
    merge = merge_pull_request(req.pr_number)
    applied = apply_env_fix(req.service_name, req.env_var, value)
    health_url = req.target_health_url or os.environ.get("TARGET_HEALTH_URL", "")
    verify = verify_recovery(health_url)
    return {"merge": merge, "apply": applied, "verify": verify}


@app.get("/incident/stream")
async def incident_stream() -> StreamingResponse:
    """Server-Sent Events stream of the agent's steps as they happen (live demo)."""
    from agents.agent import run_incident_events

    health_url = os.environ.get("TARGET_HEALTH_URL", "")
    incident_text = (
        "Incident: the Cloud Run service 'sida-target' is reported unhealthy. "
        f"Its health endpoint is {health_url}. Investigate and diagnose the single root cause."
    )

    async def gen():
        yield "retry: 60000\n\n"
        try:
            async for ev in run_incident_events(incident_text):
                if ev.get("type") == "final":
                    diagnosis = _parse_diagnosis(ev["final"])
                    ev = {
                        "type": "final",
                        "outcome": _classify_outcome(diagnosis),
                        "diagnosis": diagnosis,
                        "raw_final": ev["final"],
                    }
                yield f"data: {json.dumps(ev)}\n\n"
        except Exception as e:  # noqa: BLE001
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
        yield 'data: {"type": "done"}\n\n'

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.post("/reset")
def reset(request: Request) -> dict:
    """Re-arm the demo: break the target again and reset the config repo (for repeated judging)."""
    _check_console_key(request)
    from agents.recovery import inject_failure, reset_repo_config

    return {
        "inject": inject_failure("sida-target", "DATABASE_URL"),
        "repo_reset": reset_repo_config(),
    }


@app.get("/user-reports")
def user_reports() -> dict:
    """Return recent user-reported problems (for the console's 'user voice' panel)."""
    from agents.github_tools import get_user_reviews

    return get_user_reviews()


_last_auto_trigger = {"ts": 0.0}
_AUTO_COOLDOWN_S = 300

# In-process broadcast fabric for the persistent /events SSE channel.
# NOTE: this reaches only consoles connected to the SAME Cloud Run instance. The
# demo runs a single instance (min-instances=0 + a ~5-min warm-ping), which is
# sufficient; a multi-instance deploy would need a shared bus (Pub/Sub/Redis).
_console_subscribers: list[asyncio.Queue] = []
_SUBSCRIBER_QUEUE_MAXSIZE = 100


def _broadcast(ev: dict) -> None:
    """Fan an event out to every /events subscriber. Never raises into the caller.

    Drops the event for any full/broken queue rather than blocking a slow console
    (bounded queue + drop-on-full), so one dead client cannot stall a broadcast."""
    for q in list(_console_subscribers):
        try:
            q.put_nowait(ev)
        except Exception:  # noqa: BLE001 - QueueFull or a torn-down queue: skip it
            pass


@app.get("/events")
async def events() -> StreamingResponse:
    """Persistent, read-only SSE channel: broadcasts agent-run events (from any source,
    e.g. a Pub/Sub-triggered autonomous run) to every open console on this instance.

    Read-only observation -> intentionally unauthenticated (EventSource cannot send
    headers). Each connection gets a bounded queue; a heartbeat comment keeps the
    connection alive, and the queue is always removed on disconnect (no leak)."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=_SUBSCRIBER_QUEUE_MAXSIZE)
    _console_subscribers.append(queue)

    async def gen():
        try:
            yield "retry: 60000\n\n"
            while True:
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"  # heartbeat: keep the connection warm, avoid busy-loop
                    continue
                yield f"data: {json.dumps(ev)}\n\n"
        finally:
            try:
                _console_subscribers.remove(queue)
            except ValueError:  # already removed
                pass

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def _verify_pubsub_oidc(request: Request) -> None:
    """Verify the Google OIDC bearer token on Pub/Sub push (default-off via AUTOSRE_PUBSUB_AUDIENCE).

    When AUTOSRE_PUBSUB_AUDIENCE is unset, returns silently -> exact current behavior (deploys never
    break). When set, requires a valid Google-signed OIDC token whose aud matches. Optionally pins the
    signing service account via AUTOSRE_PUBSUB_SA_EMAIL. Raises HTTPException(403) on any failure."""
    audience = os.environ.get("AUTOSRE_PUBSUB_AUDIENCE", "")
    if not audience:
        return  # unset -> skip = exact current behavior
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=403, detail="missing bearer token")
    try:
        from google.auth.transport import requests as _gar  # lazy import (matches codebase style)
        from google.oauth2 import id_token as _idt

        claims = _idt.verify_oauth2_token(
            auth.removeprefix("Bearer "), _gar.Request(), audience=audience
        )
    except Exception:  # noqa: BLE001 - any verification failure -> reject
        raise HTTPException(status_code=403, detail="invalid token")
    expected_sa = os.environ.get("AUTOSRE_PUBSUB_SA_EMAIL", "")
    if expected_sa and not (claims.get("email") == expected_sa and claims.get("email_verified")):
        raise HTTPException(status_code=403, detail="wrong service account")


@app.post("/pubsub/incident")
async def pubsub_incident(request: Request) -> dict:
    """Pub/Sub push receiver: a Cloud Monitoring alert (target unhealthy) auto-triggers
    AutoSRE with NO human click — the agent investigates and opens a PR autonomously
    (merge + deploy still require human approval). A cooldown prevents alert storms.

    Order: OIDC verify -> tolerant envelope parse -> cooldown -> run. Verifying auth BEFORE
    stamping the cooldown prevents an unauthenticated attacker from suppressing real alerts."""
    _verify_pubsub_oidc(request)

    detail = ""
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 - empty body (curl smoke) must still succeed
        body = {}
    msg = body.get("message") if isinstance(body, dict) else None
    if isinstance(msg, dict):  # real Pub/Sub push envelope
        data = msg.get("data") or ""
        try:
            detail = base64.b64decode(data).decode("utf-8", "replace")[:1000]
        except Exception:  # noqa: BLE001 - malformed data payload -> ignore
            detail = ""
    elif isinstance(body, dict) and body:  # legacy raw-JSON body (curl tests)
        detail = json.dumps(body)[:1000]

    now = time.time()
    if now - _last_auto_trigger["ts"] < _AUTO_COOLDOWN_S:
        return {"status": "skipped", "reason": "cooldown"}
    _last_auto_trigger["ts"] = now
    from agents.agent import run_incident_events  # lazy import (matches /incident/stream)

    health_url = os.environ.get("TARGET_HEALTH_URL", "")
    incident_text = (
        "Incident auto-detected by Cloud Monitoring: the Cloud Run service 'sida-target' is unhealthy. "
        f"Its health endpoint is {health_url}. Investigate and diagnose the single root cause."
    )
    if detail:
        incident_text += f" Monitoring alert payload (verbatim): {detail}"

    # Stream the autonomous run to every open console (in-process broadcast), then
    # still return the same ack dict shape so the Pub/Sub push ack is unaffected.
    diagnosis: dict = {}
    _broadcast({"type": "run_started", "source": "pubsub"})
    try:
        async for ev in run_incident_events(incident_text):
            if ev.get("type") == "final":
                diagnosis = _parse_diagnosis(ev["final"])
                _broadcast(
                    {
                        "type": "final",
                        "outcome": _classify_outcome(diagnosis),
                        "diagnosis": diagnosis,
                        "raw_final": ev["final"],
                    }
                )
            else:
                _broadcast(ev)  # tool_call / tool_result pass through unchanged
    except Exception as e:  # noqa: BLE001 - never 500 a Pub/Sub push; always give
        # subscribers a terminal event (else the console spinner hangs forever) and
        # return a JSON ack so Pub/Sub does not retry-storm a run that will re-fail.
        _broadcast({"type": "error", "error": str(e)})
        _broadcast({"type": "done"})
        return {"status": "error", "error": str(e)[:300]}
    _broadcast({"type": "done"})

    return {
        "status": "handled",
        "outcome": _classify_outcome(diagnosis),
        "diagnosis": diagnosis,
    }
