"""Local validation of the recovery path: merge fix PR -> apply env -> verify health.

Usage (with agent venv, GITHUB_TOKEN in env):
    python scripts/test_recovery_local.py
"""
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "packages", "agent", "src")
)

os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "bero-devops-agent")
os.environ.setdefault("RUN_REGION", "asia-northeast1")
os.environ.setdefault("GITHUB_TARGET_REPO", "BERORINPO/sida-target-config")
os.environ.setdefault(
    "AUTOSRE_RESTORE_DATABASE_URL", "postgres://demo:demo@db.internal:5432/app"
)

from agents.recovery import apply_env_fix, merge_pull_request, verify_recovery  # noqa: E402

PR = int(os.environ.get("PR_NUMBER", "1"))
HEALTH = os.environ.get(
    "TARGET_HEALTH_URL",
    "https://sida-target-860561433627.asia-northeast1.run.app/health",
)

print("merge :", merge_pull_request(PR))
print("apply :", apply_env_fix("sida-target", "DATABASE_URL", os.environ["AUTOSRE_RESTORE_DATABASE_URL"]))
print("verify:", verify_recovery(HEALTH))
