# Detection pipeline: uptime check on sida-target /health -> alert policy
# -> Pub/Sub notification channel -> autosre-incidents topic -> push
# subscription -> agent /pubsub/incident.

resource "google_monitoring_uptime_check_config" "target_health" {
  display_name = "autosre-target-health"
  project      = var.project_id

  period       = "300s"
  timeout      = "10s"
  checker_type = "STATIC_IP_CHECKERS"

  http_check {
    path           = "/health"
    port           = 443
    use_ssl        = true
    request_method = "GET"

    accepted_response_status_codes {
      status_value = 200
    }
  }

  monitored_resource {
    type = "uptime_url"
    labels = {
      project_id = var.project_id
      host       = local.target_host
    }
  }

  depends_on = [google_project_service.required]
}

# Alerts are delivered as Pub/Sub messages, not email/pager: the consumer is
# the AutoSRE agent itself.
resource "google_monitoring_notification_channel" "incidents_pubsub" {
  display_name = "AutoSRE incidents (Pub/Sub)"
  project      = var.project_id
  type         = "pubsub"

  labels = {
    topic = google_pubsub_topic.incidents.id
  }

  # The Monitoring notification service agent must be able to publish to the
  # topic before the channel is verified.
  depends_on = [google_pubsub_topic_iam_member.monitoring_publisher]
}

resource "google_monitoring_alert_policy" "target_down" {
  display_name = "AutoSRE: sida-target /health down"
  project      = var.project_id
  combiner     = "OR"

  conditions {
    display_name = "Uptime check failure on sida-target /health"

    condition_threshold {
      filter = join(" AND ", [
        "metric.type=\"monitoring.googleapis.com/uptime_check/check_passed\"",
        "metric.labels.check_id=\"${google_monitoring_uptime_check_config.target_health.uptime_check_id}\"",
        "resource.type=\"uptime_url\"",
      ])

      comparison      = "COMPARISON_GT"
      threshold_value = 1
      duration        = "60s"

      aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_NEXT_OLDER"
        cross_series_reducer = "REDUCE_COUNT_FALSE"
        group_by_fields = [
          "resource.label.project_id",
          "resource.label.host",
        ]
      }

      trigger {
        count = 1
      }
    }
  }

  alert_strategy {
    auto_close = "1800s"

    # Notify only when the incident opens; the agent handles the rest of the
    # lifecycle itself (it resolves the incident by fixing the service).
    notification_prompts = ["OPENED"]
  }

  notification_channels = [
    google_monitoring_notification_channel.incidents_pubsub.id,
  ]

  documentation {
    content   = <<-EOT
      AutoSRE managed incident.

      The sida-target /health endpoint is failing its uptime check. This
      notification is published to the autosre-incidents Pub/Sub topic and
      pushed to the AutoSRE agent (sida-agent), which autonomously diagnoses
      the failure, applies the remediation on Cloud Run, verifies recovery,
      and opens a config PR with the incident report.
    EOT
    mime_type = "text/markdown"
  }
}
