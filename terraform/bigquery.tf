# Case memory — the self-improving loop's persistent store.
#
# Every diagnosed incident is written as a row in `autosre_memory.cases`, and
# the agent's recall_similar_cases tool queries it at the start of the next
# investigation. BigQuery (not an app-local store) keeps the memory where the
# operational data already lives: SQL-queryable, zero serving infrastructure,
# and joinable with Log Analytics later.
#
# Demo scale sits comfortably inside the BigQuery free tier (10 GB storage,
# 1 TB query/month): rows are ~1 KB and recall queries prune both sides of
# the self-join to a 90-day partition window.

resource "google_bigquery_dataset" "autosre_memory" {
  dataset_id  = "autosre_memory"
  description = "AutoSRE case memory: diagnosed incidents + human-approved recovery outcomes"
  location    = var.region

  depends_on = [google_project_service.required]
}

resource "google_bigquery_table" "cases" {
  dataset_id = google_bigquery_dataset.autosre_memory.dataset_id
  table_id   = "cases"

  # Demo/hackathon lifecycle: allow `terraform destroy` to clean up.
  deletion_protection = false

  time_partitioning {
    type  = "DAY"
    field = "ts"
  }

  schema = jsonencode([
    { name = "kind", type = "STRING", mode = "REQUIRED",
    description = "diagnosis | resolution" },
    { name = "case_id", type = "STRING", mode = "REQUIRED" },
    { name = "ts", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "service", type = "STRING", mode = "NULLABLE" },
    { name = "source", type = "STRING", mode = "NULLABLE",
    description = "manual | console | pubsub" },
    { name = "root_cause", type = "STRING", mode = "NULLABLE" },
    { name = "missing_env_var", type = "STRING", mode = "NULLABLE" },
    { name = "action", type = "STRING", mode = "NULLABLE",
    description = "fix_pr | escalate | none" },
    { name = "confidence", type = "FLOAT", mode = "NULLABLE" },
    { name = "pr_url", type = "STRING", mode = "NULLABLE" },
    { name = "pr_number", type = "INTEGER", mode = "NULLABLE",
    description = "join key between a diagnosis and its resolution" },
    { name = "user_reports_summary", type = "STRING", mode = "NULLABLE" },
    { name = "recovered", type = "BOOLEAN", mode = "NULLABLE",
    description = "resolution rows: did 503->200 verification succeed after approval" },
    { name = "duration_s", type = "FLOAT", mode = "NULLABLE" },
  ])
}

# The runtime SA writes case rows (streaming insert) and reads them back
# (recall query). Scoped to this dataset only — no project-wide data access.
resource "google_bigquery_dataset_iam_member" "runtime_sa_data_editor" {
  dataset_id = google_bigquery_dataset.autosre_memory.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${local.runtime_sa}"
}
