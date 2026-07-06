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

REQUIRED_ENV = "DATABASE_URL"


@app.get("/")
def root() -> dict:
    return {"service": "target-service", "db_configured": bool(os.environ.get(REQUIRED_ENV))}


# NOTE: "/healthz" is reserved by the Cloud Run front end (GFE 404s it before
# it reaches the container). Expose the health check at "/health" instead.
@app.get("/health")
def health():
    value = os.environ.get(REQUIRED_ENV)
    if not value:
        # Log the boot-time failure so AutoSRE can find the root cause in Cloud Logging.
        print(f'{{"severity":"ERROR","message":"startup check failed: required env var {REQUIRED_ENV} is not set"}}', flush=True)
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "reason": f"required env var {REQUIRED_ENV} is not set"},
        )
    return {"status": "ok"}
