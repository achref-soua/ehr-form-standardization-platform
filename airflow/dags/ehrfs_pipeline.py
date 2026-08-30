"""Optional scheduling adapter; all clinical logic remains in EHRFS services."""

from __future__ import annotations

from datetime import UTC, datetime

from airflow.sdk import DAG, task

with DAG(
    dag_id="ehrfs_bounded_pipeline",
    start_date=datetime(2026, 1, 1, tzinfo=UTC),
    schedule=None,
    catchup=False,
    tags=["ehrfs", "adapter-only"],
) as dag:

    @task
    def enqueue(batch_id: str, form_version: str) -> dict[str, str]:
        """Return the service request that an authenticated deployment adapter submits."""
        return {"batch_id": batch_id, "form_version": form_version}

    enqueue("scheduled-synthetic-batch", "3")
