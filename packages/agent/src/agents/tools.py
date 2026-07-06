"""AutoSRE investigation tools (read-only), exposed to the ReAct agent.

Each function becomes a Gemini function-calling tool. They read REAL state from
Google Cloud (Cloud Run config/status, Cloud Logging) and the live target
service, so the agent's diagnosis is grounded in evidence, not guesses.

ADK/Gemini build the tool schema from the type hints + docstrings below, so keep
the signatures simple (str/int in, dict out) and the docstrings accurate.
"""
import os

import httpx

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
# Cloud Run services live in a real region even when Vertex uses "global".
RUN_REGION = os.environ.get("RUN_REGION", "asia-northeast1")


def _service_path(service_name: str) -> str:
    return f"projects/{PROJECT}/locations/{RUN_REGION}/services/{service_name}"


def get_service_status(service_name: str) -> dict:
    """Get the deploy status of a Cloud Run service: latest revision and ready conditions.

    Args:
        service_name: the Cloud Run service name, e.g. "sida-target".
    """
    try:
        from google.cloud import run_v2

        client = run_v2.ServicesClient()
        svc = client.get_service(name=_service_path(service_name))
        conditions = [
            {
                "type": c.type_,
                "state": run_v2.Condition.State(c.state).name,
                "message": c.message,
            }
            for c in svc.conditions
        ]
        return {
            "ok": True,
            "service": service_name,
            "uri": svc.uri,
            "latest_ready_revision": (svc.latest_ready_revision or "").split("/")[-1] or None,
            "latest_created_revision": (svc.latest_created_revision or "").split("/")[-1] or None,
            "terminal_condition": {
                "type": svc.terminal_condition.type_,
                "state": run_v2.Condition.State(svc.terminal_condition.state).name,
                "message": svc.terminal_condition.message,
            },
            "conditions": conditions,
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def get_service_config(service_name: str) -> dict:
    """Get the deployed container config of a Cloud Run service: image and environment variable names/values.

    Args:
        service_name: the Cloud Run service name, e.g. "sida-target".
    """
    try:
        from google.cloud import run_v2

        client = run_v2.ServicesClient()
        svc = client.get_service(name=_service_path(service_name))
        containers = list(svc.template.containers)
        c = containers[0] if containers else None
        env = {e.name: (e.value if e.value else "<from-secret>") for e in (c.env if c else [])}
        return {
            "ok": True,
            "service": service_name,
            "image": c.image if c else None,
            "env_vars": env,
            "env_var_names": sorted(env.keys()),
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def get_recent_logs(service_name: str, limit: int = 20) -> dict:
    """Get the most recent Cloud Logging entries for a Cloud Run service (newest first).

    Args:
        service_name: the Cloud Run service name, e.g. "sida-target".
        limit: max number of log lines to return (default 20, capped at 50).
    """
    try:
        from google.cloud import logging as gcloud_logging

        client = gcloud_logging.Client(project=PROJECT)
        flt = (
            'resource.type="cloud_run_revision" '
            f'AND resource.labels.service_name="{service_name}"'
        )
        entries = []
        for entry in client.list_entries(
            filter_=flt, order_by=gcloud_logging.DESCENDING, page_size=min(limit, 50)
        ):
            payload = entry.payload
            text = payload if isinstance(payload, str) else str(payload)
            entries.append({"severity": entry.severity, "text": text[:300]})
            if len(entries) >= min(limit, 50):
                break
        return {"ok": True, "service": service_name, "count": len(entries), "entries": entries}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def probe_health(url: str) -> dict:
    """HTTP GET a URL (e.g. the target service's /health) and report the status code and body.

    Args:
        url: full URL to probe, e.g. "https://sida-target-xxx.run.app/health".
    """
    try:
        r = httpx.get(url, timeout=10.0)
        return {
            "ok": True,
            "url": url,
            "status_code": r.status_code,
            "healthy": r.status_code == 200,
            "body": r.text[:300],
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "url": url, "error": f"{type(e).__name__}: {e}"}
