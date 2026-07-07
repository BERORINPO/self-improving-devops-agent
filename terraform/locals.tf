data "google_project" "this" {
  project_id = var.project_id
}

locals {
  project_number = data.google_project.this.number

  # Live deployment runs as the Compute Engine default service account.
  runtime_sa = (
    var.runtime_service_account_email != ""
    ? var.runtime_service_account_email
    : "${local.project_number}-compute@developer.gserviceaccount.com"
  )

  # Cloud Run deterministic URLs (https://SERVICE-PROJECTNUMBER.REGION.run.app).
  # Computing them instead of referencing the service resources avoids the
  # self-reference cycle: sida-agent's own env vars (AUTOSRE_PUBSUB_AUDIENCE)
  # embed the agent's own URL.
  agent_host  = "sida-agent-${local.project_number}.${var.region}.run.app"
  agent_url   = "https://${local.agent_host}"
  target_host = "sida-target-${local.project_number}.${var.region}.run.app"
  target_url  = "https://${local.target_host}"

  # Images built by `gcloud run deploy --source` land in this repository.
  agent_image = (
    var.agent_image != ""
    ? var.agent_image
    : "${var.region}-docker.pkg.dev/${var.project_id}/cloud-run-source-deploy/sida-agent"
  )
  target_image = (
    var.target_image != ""
    ? var.target_image
    : "${var.region}-docker.pkg.dev/${var.project_id}/cloud-run-source-deploy/sida-target"
  )

  # Google-managed service agent that publishes Monitoring notifications.
  monitoring_notification_sa = "service-${local.project_number}@gcp-sa-monitoring-notification.iam.gserviceaccount.com"
}
