# GitHub PAT used by the agent to open remediation PRs against
# var.github_target_repo.
#
# Terraform manages the secret CONTAINER only. The value is added
# out-of-band so the token never enters Terraform state:
#
#   printf '%s' "$GITHUB_PAT" | gcloud secrets versions add github-pat \
#     --project <project_id> --data-file=-
#
# See README.md, step 4.
resource "google_secret_manager_secret" "github_pat" {
  secret_id = "github-pat"
  project   = var.project_id

  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}
