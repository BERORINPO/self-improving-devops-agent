"""AutoSRE demo target-service.

A trivial "production" app that is healthy only when DATABASE_URL is set.

  - Deployed WITHOUT DATABASE_URL  => /healthz returns 503  (the incident)
  - Redeployed WITH DATABASE_URL   => /healthz returns 200  (recovered)

The container always boots (uvicorn binds $PORT), so Cloud Run keeps a serving
revision. The failure surfaces as a 503 on /healthz, which AutoSRE detects from
the outside, diagnoses (missing env var, via logs + config), fixes (re-adds the
env var through a PR), and verifies (polls /healthz until 200).
"""
import os

from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="target-service")

# Comma-separated list of env vars the app requires to be healthy. Default is a
# single "DATABASE_URL" so the existing demo behaves byte-identically; set
# REQUIRED_ENV_VARS (e.g. "DATABASE_URL,SECRET_KEY") to arm the multi-var scenario.
REQUIRED_ENVS = [v.strip() for v in os.environ.get("REQUIRED_ENV_VARS", "DATABASE_URL").split(",") if v.strip()]


@app.get("/")
def root() -> dict:
    return {"service": "target-service", "db_configured": all(bool(os.environ.get(name)) for name in REQUIRED_ENVS)}


# NOTE: "/healthz" is reserved by the Cloud Run front end (GFE 404s it before
# it reaches the container). Expose the health check at "/health" instead.
@app.get("/health")
def health():
    for name in REQUIRED_ENVS:
        if not os.environ.get(name):
            # Log the boot-time failure so AutoSRE can find the root cause in Cloud Logging.
            print(f'{{"severity":"ERROR","message":"startup check failed: required env var {name} is not set"}}', flush=True)
            return JSONResponse(
                status_code=503,
                content={"status": "unhealthy", "reason": f"required env var {name} is not set"},
            )
    return {"status": "ok"}
