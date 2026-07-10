"""GitHub PR tool for AutoSRE.

open_pull_request() opens a REAL pull request that fixes the incident by restoring
a missing environment variable in the target deploy-config repo. This is the
load-bearing DevOps artifact and a permanent, clickable proof for the demo.

Opening the PR is autonomous; merging + redeploying is human-gated (not here).

Env:
  GITHUB_TOKEN        classic PAT with 'repo' scope (mounted from Secret Manager)
  GITHUB_TARGET_REPO  "owner/name", e.g. "BERORINPO/sida-target-config"
  TARGET_CONFIG_PATH  path to the env file (default "deploy/target-service.env")
"""
import base64
import os

import httpx

API = "https://api.github.com"
CONFIG_PATH = os.environ.get("TARGET_CONFIG_PATH", "deploy/target-service.env")
# Safety guard: the agent may only open PRs that restore an env var on this allowlist.
# This stops a hallucinated or prompt-injected "fix" (e.g. SECRET_KEY) from ever
# becoming a real PR, no matter what the model outputs.
def allowed_env_vars() -> set:
    """The remediation allowlist, read from env at CALL time (not import time).

    Production sets AUTOSRE_ALLOWED_ENV_VARS once at deploy, so behavior there is
    identical to a module constant. Call-time reading matters for eval REAL mode,
    where scenario-scoped env (e.g. S02's extended allowlist) must reach both this
    guard and the agent instruction built from it.

    NOTE: this guard is the injection backstop. If a code path is ever added that
    sets AUTOSRE_ALLOWED_ENV_VARS from user-controllable input mid-process,
    re-evaluate call-time reading here first (an attacker could widen the set).
    """
    return {
        v.strip()
        for v in os.environ.get("AUTOSRE_ALLOWED_ENV_VARS", "DATABASE_URL").split(",")
        if v.strip()
    }


def _repo() -> str:
    return os.environ.get("GITHUB_TARGET_REPO", "")


def _headers() -> dict:
    token = os.environ["GITHUB_TOKEN"]
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def get_user_reviews(limit: int = 10) -> dict:
    """Read recent user-reported problems (open issues labeled 'user-report') from the project tracker.

    These are REAL user complaints. Read them first to understand the user-facing symptom
    before investigating the system.

    Args:
        limit: max number of user reports to return (default 10).
    """
    repo = _repo()
    try:
        with httpx.Client(base_url=API, headers=_headers(), timeout=20.0) as c:
            r = c.get(
                f"/repos/{repo}/issues",
                params={"state": "open", "labels": "user-report", "per_page": limit},
            )
            r.raise_for_status()
            reviews = [
                {
                    "number": i["number"],
                    "title": i["title"],
                    "body": (i.get("body") or "")[:300],
                    "user": i["user"]["login"],
                    "created_at": i["created_at"],
                }
                for i in r.json()
                if "pull_request" not in i
            ]
            # Second-layer injection screen (Model Armor; default-off no-op).
            # Flags a prompt-injection / jailbreak embedded in a user report so the
            # agent and console can see it — the open_pull_request allowlist guard
            # is still the backstop that makes an injected "fix" impossible.
            from agents.armor_tools import screen_text  # lazy import (default-off)

            armor = screen_text(
                "\n".join(f"{r['title']}\n{r['body']}" for r in reviews),
                source="user_report",
            )
            return {"ok": True, "count": len(reviews), "reviews": reviews, "armor": armor}
    except httpx.HTTPStatusError as e:
        return {"ok": False, "error": f"GitHub {e.response.status_code}: {e.response.text[:200]}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def open_pull_request(missing_env_var: str, root_cause: str) -> dict:
    """Open a real GitHub pull request that fixes the incident by restoring a missing environment variable in the target deploy config.

    Args:
        missing_env_var: the environment variable to restore, e.g. "DATABASE_URL".
        root_cause: a one-line root-cause summary for the PR description.
    """
    try:
        repo = _repo()
        allowed = allowed_env_vars()
        if missing_env_var not in allowed:
            return {
                "ok": False,
                "error": f"'{missing_env_var}' is not in the allowed remediation set "
                f"{sorted(allowed)}; refusing to open a PR (safety guard against "
                f"hallucinated or injected fixes)",
            }
        # The canonical restore value is configured out-of-band (not guessed by
        # the model), so the fix is deterministic and matches what recovery applies.
        env_value = os.environ.get(f"AUTOSRE_RESTORE_{missing_env_var}", "<restore-value-unavailable>")
        branch = f"autosre/fix-{missing_env_var.lower()}"
        with httpx.Client(base_url=API, headers=_headers(), timeout=20.0) as c:
            base_sha = (
                c.get(f"/repos/{repo}/git/ref/heads/main").raise_for_status().json()
            )["object"]["sha"]

            f = (
                c.get(f"/repos/{repo}/contents/{CONFIG_PATH}", params={"ref": "main"})
                .raise_for_status()
                .json()
            )
            file_sha = f["sha"]
            current = base64.b64decode(f["content"]).decode("utf-8")
            if f"{missing_env_var}=" in current:
                return {"ok": False, "error": f"{missing_env_var} already present in {CONFIG_PATH}"}

            # Idempotent for repeated demo runs: drop any stale branch first.
            c.delete(f"/repos/{repo}/git/refs/heads/{branch}")
            c.post(
                f"/repos/{repo}/git/refs",
                json={"ref": f"refs/heads/{branch}", "sha": base_sha},
            ).raise_for_status()

            new_content = current.rstrip("\n") + f"\n{missing_env_var}={env_value}\n"
            c.put(
                f"/repos/{repo}/contents/{CONFIG_PATH}",
                json={
                    "message": f"fix: restore {missing_env_var} to recover sida-target",
                    "content": base64.b64encode(new_content.encode("utf-8")).decode("ascii"),
                    "sha": file_sha,
                    "branch": branch,
                },
            ).raise_for_status()

            pr_body = (
                "## AutoSRE automated fix\n\n"
                f"**Root cause:** {root_cause}\n\n"
                f"**Fix:** restore `{missing_env_var}` in `{CONFIG_PATH}`.\n\n"
                "Opened autonomously by AutoSRE after investigating the live Cloud Run "
                "status, logs, and deployed config. Merge + redeploy require human approval."
            )
            pr = (
                c.post(
                    f"/repos/{repo}/pulls",
                    json={
                        "title": f"fix: restore {missing_env_var} to recover sida-target",
                        "head": branch,
                        "base": "main",
                        "body": pr_body,
                    },
                )
                .raise_for_status()
                .json()
            )
            return {
                "ok": True,
                "pr_number": pr["number"],
                "pr_url": pr["html_url"],
                "branch": branch,
            }
    except httpx.HTTPStatusError as e:
        return {"ok": False, "error": f"GitHub {e.response.status_code}: {e.response.text[:300]}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
