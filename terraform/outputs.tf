output "agent_url" {
  description = "Base URL of the AutoSRE agent (sida-agent) Cloud Run service."
  value       = google_cloud_run_v2_service.agent.uri
}

output "target_url" {
  description = "Base URL of the demo target (sida-target) Cloud Run service."
  value       = google_cloud_run_v2_service.target.uri
}
