# Project-level roles for the runtime service account (the Compute Engine
# default SA in the live deployment). Verified against the live project:
#
#   roles/aiplatform.user             - call Vertex AI (Gemini) from the agent
#   roles/logging.viewer              - read target logs during diagnosis
#   roles/run.viewer                  - inspect Cloud Run service state
#   roles/run.developer               - patch sida-target env (the remediation)
#   roles/secretmanager.secretAccessor - read github-pat at revision startup
#   roles/bigquery.jobUser            - run recall queries against case memory
#     (table data access is granted at dataset level in bigquery.tf)
resource "google_project_iam_member" "runtime_sa_roles" {
  for_each = toset([
    "roles/aiplatform.user",
    "roles/logging.viewer",
    "roles/run.viewer",
    "roles/run.developer",
    "roles/secretmanager.secretAccessor",
    "roles/bigquery.jobUser",
  ])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${local.runtime_sa}"

  depends_on = [google_project_service.required]
}

# Required on a fresh project so Pub/Sub can mint OIDC tokens as the runtime
# SA for the push subscription. (On long-lived projects this grant often
# already exists; it is idempotent and mirrors what the push subscription
# needs to function.)
resource "google_project_iam_member" "pubsub_token_creator" {
  project = var.project_id
  role    = "roles/iam.serviceAccountTokenCreator"
  member  = "serviceAccount:service-${local.project_number}@gcp-sa-pubsub.iam.gserviceaccount.com"

  depends_on = [google_project_service.required]
}
