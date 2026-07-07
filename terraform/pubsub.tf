# Incident fan-in: Cloud Monitoring publishes alert notifications to this
# topic; the push subscription delivers them to the agent's /pubsub/incident
# endpoint with an OIDC token (verified by the agent against
# AUTOSRE_PUBSUB_AUDIENCE / AUTOSRE_PUBSUB_SA_EMAIL).

resource "google_pubsub_topic" "incidents" {
  name    = "autosre-incidents"
  project = var.project_id

  depends_on = [google_project_service.required]
}

resource "google_pubsub_subscription" "incidents_push" {
  name    = "autosre-incidents-push"
  project = var.project_id
  topic   = google_pubsub_topic.incidents.id

  ack_deadline_seconds = 120

  push_config {
    push_endpoint = "${local.agent_url}/pubsub/incident"

    oidc_token {
      service_account_email = local.runtime_sa
      # audience defaults to the push endpoint, which matches the agent's
      # AUTOSRE_PUBSUB_AUDIENCE env var.
    }
  }
}

# Allow the Cloud Monitoring notification service agent to publish alerts.
resource "google_pubsub_topic_iam_member" "monitoring_publisher" {
  project = var.project_id
  topic   = google_pubsub_topic.incidents.name
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${local.monitoring_notification_sa}"
}
