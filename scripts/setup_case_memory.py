"""One-shot setup for the case-memory BigQuery store (terraform/bigquery.tf mirror).

The terraform definition is the IaC source of truth, but no terraform state has
been applied to the project; this script creates the same dataset + partitioned
table imperatively so the self-improving loop can be enabled without a full
`terraform apply` (which would try to adopt every other already-manually-created
resource). Idempotent: safe to re-run (exists_ok on both resources).

Usage (from the repo root, any interpreter with google-cloud-bigquery):
  .venv-eval\\Scripts\\python.exe scripts\\setup_case_memory.py

IAM note: no grants are made here. The Cloud Run runtime SA currently holds
roles/editor (default compute SA), which covers the dataset write + query paths.
Trimming editor down to the terraform-scoped roles (dataset dataEditor +
project jobUser) is tracked as a post-judging hardening item (7/24 gate).
"""
import os

from google.cloud import bigquery

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "bero-devops-agent")
LOCATION = "asia-northeast1"  # matches var.region in terraform


def main() -> None:
    client = bigquery.Client(project=PROJECT)

    ds = bigquery.Dataset(f"{PROJECT}.autosre_memory")
    ds.location = LOCATION
    ds.description = (
        "AutoSRE case memory: diagnosed incidents + human-approved recovery outcomes"
    )
    ds = client.create_dataset(ds, exists_ok=True)
    print(f"dataset ok: {ds.dataset_id} ({ds.location})")

    # Schema mirrors terraform/bigquery.tf exactly — keep the two in sync.
    schema = [
        bigquery.SchemaField("kind", "STRING", mode="REQUIRED",
                             description="diagnosis | resolution"),
        bigquery.SchemaField("case_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("ts", "TIMESTAMP", mode="REQUIRED"),
        bigquery.SchemaField("service", "STRING"),
        bigquery.SchemaField("source", "STRING", description="manual | console | pubsub"),
        bigquery.SchemaField("root_cause", "STRING"),
        bigquery.SchemaField("missing_env_var", "STRING"),
        bigquery.SchemaField("action", "STRING", description="fix_pr | escalate | none"),
        bigquery.SchemaField("confidence", "FLOAT"),
        bigquery.SchemaField("pr_url", "STRING"),
        bigquery.SchemaField("pr_number", "INTEGER",
                             description="join key between a diagnosis and its resolution"),
        bigquery.SchemaField("user_reports_summary", "STRING"),
        bigquery.SchemaField("recovered", "BOOLEAN",
                             description="resolution rows: did 503->200 verification succeed after approval"),
        bigquery.SchemaField("duration_s", "FLOAT"),
    ]
    table = bigquery.Table(f"{PROJECT}.autosre_memory.cases", schema=schema)
    table.time_partitioning = bigquery.TimePartitioning(
        type_=bigquery.TimePartitioningType.DAY, field="ts")
    table = client.create_table(table, exists_ok=True)
    print(f"table ok: {table.dataset_id}.{table.table_id} "
          f"(partitioned on {table.time_partitioning.field}, rows={table.num_rows})")


if __name__ == "__main__":
    main()
