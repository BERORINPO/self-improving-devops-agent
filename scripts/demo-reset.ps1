<#
.SYNOPSIS
  Reset the AutoSRE demo to a clean "incident live" state before recording.

.DESCRIPTION
  1. Removes DATABASE_URL from the target Cloud Run service  -> /health 503.
  2. Resets the config repo (deploy/target-service.env on main) to the broken
     state so the agent's next PR cleanly re-adds DATABASE_URL.
  The previous open fix PR is automatically superseded on the next agent run
  (open_pull_request recreates the branch), so no manual PR cleanup is needed.

.EXAMPLE
  pwsh scripts/demo-reset.ps1
#>
$ErrorActionPreference = "Stop"
$repo = "BERORINPO/sida-target-config"
$path = "deploy/target-service.env"

Write-Output "[1/2] breaking target (remove DATABASE_URL)..."
# Remove DATABASE_URL to arm the incident. Also (re-)set SECRET_KEY in the SAME
# update so that if the target is armed with REQUIRED_ENV_VARS=DATABASE_URL,SECRET_KEY,
# only DATABASE_URL ends up missing and the main demo's reason stays "DATABASE_URL".
# This is additive and idempotent: in the default single-var demo, SECRET_KEY is
# simply present-but-unused, so /health still reports DATABASE_URL as the only gap.
gcloud run services update sida-target `
  --project bero-devops-agent --region asia-northeast1 `
  --remove-env-vars DATABASE_URL `
  "--update-env-vars=SECRET_KEY=demo-secret-0000-rotate-me" `
  --quiet 2>&1 | Select-Object -Last 1

Write-Output "[2/2] resetting config repo to broken state..."
$sha = gh api "repos/$repo/contents/$path" --jq ".sha"
$broken = @"
# Deploy configuration for the sida-target Cloud Run service.
# NOTE: DATABASE_URL is required by the app at runtime but is currently absent.
# This is the incident AutoSRE detects and fixes via a pull request.
SERVICE_NAME=sida-target
REGION=asia-northeast1
LOG_LEVEL=info
"@
$b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($broken))
gh api --method PUT "repos/$repo/contents/$path" `
  -f message="chore: reset demo state (remove DATABASE_URL)" `
  -f content="$b64" -f sha="$sha" 2>&1 | Out-Null

Write-Output "done. Target is 503, repo config is broken. Open the console and click 'Run AutoSRE'."
