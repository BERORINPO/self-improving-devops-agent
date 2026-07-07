# Cloud Scheduler jobs.

# Re-arms the demo every hour: POSTs to the agent's /reset endpoint, which
# breaks sida-target again (removes DATABASE_URL) so the next uptime failure
# triggers a fresh autonomous incident run.
#
# Deliberately NO OIDC on this job: /reset authenticates via the ?key=
# query parameter (the console key), matching the live deployment.
resource "google_cloud_scheduler_job" "demo_rearm" {
  name    = "autosre-demo-rearm"
  project = var.project_id
  region  = var.region

  schedule         = "0 * * * *"
  time_zone        = "Asia/Tokyo"
  attempt_deadline = "320s"

  http_target {
    http_method = "POST"
    uri         = "${local.agent_url}/reset?key=${var.console_key}"
    body        = base64encode("{}")

    headers = {
      "Content-Type" = "application/octet-stream"
    }
  }

  depends_on = [google_project_service.required]
}

# Free cold-start mitigation: pings /health every 5 minutes so the agent
# container stays warm without paying for min-instances.
resource "google_cloud_scheduler_job" "warm_ping" {
  name    = "autosre-warm-ping"
  project = var.project_id
  region  = var.region

  schedule  = "*/5 * * * *"
  time_zone = "Asia/Tokyo"

  http_target {
    http_method = "GET"
    uri         = "${local.agent_url}/health"
  }

  depends_on = [google_project_service.required]
}
