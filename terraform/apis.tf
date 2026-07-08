# APIs required by the stack. Enabled here so `terraform apply` on a fresh
# project works without manual `gcloud services enable` steps.
resource "google_project_service" "required" {
  for_each = toset([
    "run.googleapis.com",              # Cloud Run services
    "compute.googleapis.com",          # Compute default service account
    "pubsub.googleapis.com",           # incident topic + push subscription
    "cloudscheduler.googleapis.com",   # re-arm + warm-ping jobs
    "secretmanager.googleapis.com",    # github-pat secret
    "monitoring.googleapis.com",       # uptime check + alert policy
    "aiplatform.googleapis.com",       # Vertex AI (GOOGLE_GENAI_USE_VERTEXAI=TRUE)
    "cloudbuild.googleapis.com",       # gcloud run deploy --source builds
    "artifactregistry.googleapis.com", # cloud-run-source-deploy repository
    "logging.googleapis.com",          # agent reads logs during diagnosis
    "bigquery.googleapis.com",         # case memory (self-improving loop)
  ])

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}
