<#
.SYNOPSIS
  Inject or restore the AutoSRE demo incident on the target Cloud Run service.

.DESCRIPTION
  inject  : remove DATABASE_URL from sida-target -> /health returns 503 (the incident).
  restore : re-add DATABASE_URL                  -> /health returns 200 (recovered).

  This deterministic on-demand trigger replaces Cloud Monitoring + Pub/Sub for the demo.

.EXAMPLE
  pwsh scripts/target-incident.ps1 -Action inject
  pwsh scripts/target-incident.ps1 -Action restore
#>
param(
  [ValidateSet("inject", "restore")]
  [string]$Action = "inject",
  [string]$EnvVar = "DATABASE_URL"
)

# Demo restore values keyed by env var name. DATABASE_URL keeps the original
# demo value so the default path is unchanged; SECRET_KEY supports the
# escalation (out-of-policy) scenario.
$restoreValues = @{
  DATABASE_URL = "postgres://demo:demo@db.internal:5432/app"
  SECRET_KEY   = "demo-secret-0000-rotate-me"
}

$common = @(
  "run", "services", "update", "sida-target",
  "--project", "bero-devops-agent",
  "--region", "asia-northeast1",
  "--quiet"
)

if ($Action -eq "inject") {
  gcloud @common --remove-env-vars $EnvVar
  Write-Output "[inject] $EnvVar removed from sida-target. /health -> 503 (incident live)."
}
else {
  # Quote the whole flag so PowerShell does not array-split on any comma.
  gcloud @common "--update-env-vars=$EnvVar=$($restoreValues[$EnvVar])"
  Write-Output "[restore] $EnvVar re-added to sida-target. /health -> 200 (recovered)."
}
