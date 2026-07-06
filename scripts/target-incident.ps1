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
  [string]$Action = "inject"
)

$common = @(
  "run", "services", "update", "sida-target",
  "--project", "bero-devops-agent",
  "--region", "asia-northeast1",
  "--quiet"
)

if ($Action -eq "inject") {
  gcloud @common --remove-env-vars DATABASE_URL
  Write-Output "[inject] DATABASE_URL removed from sida-target. /health -> 503 (incident live)."
}
else {
  # Quote the whole flag so PowerShell does not array-split on any comma.
  gcloud @common "--update-env-vars=DATABASE_URL=postgres://demo:demo@db.internal:5432/app"
  Write-Output "[restore] DATABASE_URL re-added to sida-target. /health -> 200 (recovered)."
}
