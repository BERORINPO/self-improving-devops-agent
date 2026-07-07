variable "project_id" {
  description = "GCP project id that hosts the AutoSRE stack (live demo: bero-devops-agent)."
  type        = string
}

variable "region" {
  description = "Region for Cloud Run, Cloud Scheduler and Artifact Registry."
  type        = string
  default     = "asia-northeast1"
}

variable "github_target_repo" {
  description = "GitHub repo (owner/name) the agent opens remediation PRs against."
  type        = string
  default     = "BERORINPO/sida-target-config"
}

variable "console_key" {
  description = <<-EOT
    Shared key for the agent's operator console and /reset endpoint.
    The demo-rearm Scheduler job passes it as a query parameter because the
    endpoint validates the key itself (no OIDC on that job by design).
  EOT
  type        = string
  sensitive   = true
}

variable "restore_database_url" {
  description = <<-EOT
    Value injected as AUTOSRE_RESTORE_DATABASE_URL on the agent. In the live
    demo this is a stand-in DSN the agent "restores" onto the broken target;
    it is not a real reachable database.
  EOT
  type        = string
  default     = "postgres://demo:demo@db.internal:5432/app"
}

variable "runtime_service_account_email" {
  description = <<-EOT
    Service account both Cloud Run services run as, and which Pub/Sub uses to
    mint OIDC tokens for the push subscription. Leave empty to use the Compute
    Engine default service account (<project-number>-compute@developer.gserviceaccount.com),
    which is what the live deployment uses.
  EOT
  type        = string
  default     = ""
}

variable "agent_image" {
  description = <<-EOT
    Container image for the sida-agent service. Leave empty to use the
    Artifact Registry path produced by `gcloud run deploy sida-agent --source .`
    (repository cloud-run-source-deploy). That command is the image bootstrap
    on a fresh project - see README.md.
  EOT
  type        = string
  default     = ""
}

variable "target_image" {
  description = <<-EOT
    Container image for the sida-target service. Leave empty to use the
    Artifact Registry path produced by `gcloud run deploy sida-target --source .`
    (repository cloud-run-source-deploy). See README.md.
  EOT
  type        = string
  default     = ""
}

variable "target_secret_key" {
  description = <<-EOT
    SECRET_KEY env var on sida-target. Intentionally a throwaway demo value:
    the target app is a deliberately fragile demo workload.
  EOT
  type        = string
  default     = "demo-secret-0000-rotate-me"
}
