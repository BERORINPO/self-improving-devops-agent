"""AutoSRE recovery — the human-gated actions.

After a human approves, AutoSRE: (1) merges the fix PR, (2) applies the restored
env var to the target Cloud Run service, and (3) verifies the target is healthy
again. Merge + apply + redeploy are exactly the steps that require approval.
"""
import base64
import os
import time

import httpx

API = "https://api.github.com"
PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
RUN_REGION = os.environ.get("RUN_REGION", "asia-northeast1")


def _gh_headers() -> dict:
    return {
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def merge_pull_request(pr_number: int) -> dict:
    """Merge the AutoSRE fix PR (squash)."""
    repo = os.environ.get("GITHUB_TARGET_REPO", "")
    try:
        with httpx.Client(base_url=API, headers=_gh_headers(), timeout=20.0) as c:
            r = c.put(
                f"/repos/{repo}/pulls/{pr_number}/merge", json={"merge_method": "squash"}
            )
            r.raise_for_status()
            data = r.json()
            return {"ok": True, "merged": data.get("merged", True), "sha": data.get("sha")}
    except httpx.HTTPStatusError as e:
        return {"ok": False, "error": f"GitHub {e.response.status_code}: {e.response.text[:300]}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def apply_env_fix(service_name: str, env_var: str, value: str) -> dict:
    """Add/update an env var on the target Cloud Run service (deploys a new revision)."""
    try:
        from google.cloud import run_v2

        client = run_v2.ServicesClient()
        name = f"projects/{PROJECT}/locations/{RUN_REGION}/services/{service_name}"
        svc = client.get_service(name=name)
        container = svc.template.containers[0]
        for e in container.env:
            if e.name == env_var:
                e.value = value
                break
        else:
            container.env.append(run_v2.EnvVar(name=env_var, value=value))
        op = client.update_service(service=svc)
        op.result(timeout=300)
        return {"ok": True, "service": service_name, "applied_env_var": env_var}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def verify_recovery(health_url: str, timeout_s: int = 150) -> dict:
    """Poll the target health URL until it returns 200 (recovered) or the timeout elapses."""
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        try:
            r = httpx.get(health_url, timeout=10.0)
            last = r.status_code
            if r.status_code == 200:
                return {"ok": True, "recovered": True, "status_code": 200, "body": r.text[:200]}
        except Exception as e:  # noqa: BLE001
            last = f"error: {e}"
        time.sleep(5)
    return {"ok": True, "recovered": False, "last_status": last}


def inject_failure(service_name: str, env_var: str) -> dict:
    """Remove an env var from the target Cloud Run service (re-arms the incident)."""
    try:
        from google.cloud import run_v2

        client = run_v2.ServicesClient()
        name = f"projects/{PROJECT}/locations/{RUN_REGION}/services/{service_name}"
        svc = client.get_service(name=name)
        container = svc.template.containers[0]
        keep = [
            run_v2.EnvVar(name=e.name, value=e.value)
            for e in container.env
            if e.name != env_var
        ]
        del container.env[:]
        container.env.extend(keep)
        op = client.update_service(service=svc)
        op.result(timeout=300)
        return {"ok": True, "removed": env_var}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def reset_repo_config() -> dict:
    """Reset the config repo file to the broken state (DATABASE_URL absent)."""
    repo = os.environ.get("GITHUB_TARGET_REPO", "")
    path = os.environ.get("TARGET_CONFIG_PATH", "deploy/target-service.env")
    broken = (
        "# Deploy configuration for the sida-target Cloud Run service.\n"
        "# NOTE: DATABASE_URL is required by the app at runtime but is currently absent.\n"
        "# This is the incident AutoSRE detects and fixes via a pull request.\n"
        "SERVICE_NAME=sida-target\nREGION=asia-northeast1\nLOG_LEVEL=info\n"
    )
    try:
        with httpx.Client(base_url=API, headers=_gh_headers(), timeout=20.0) as c:
            f = c.get(f"/repos/{repo}/contents/{path}").raise_for_status().json()
            c.put(
                f"/repos/{repo}/contents/{path}",
                json={
                    "message": "chore: reset demo state (remove DATABASE_URL)",
                    "content": base64.b64encode(broken.encode("utf-8")).decode("ascii"),
                    "sha": f["sha"],
                },
            ).raise_for_status()
        return {"ok": True}
    except httpx.HTTPStatusError as e:
        return {"ok": False, "error": f"GitHub {e.response.status_code}: {e.response.text[:200]}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
