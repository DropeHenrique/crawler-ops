"""
### Captura de produtos (alpha + beta)

1. **enqueue_batch**: publica um lote de jobs no SQS (`capture-jobs`).
2. **wait_batch**: sensor que aguarda todos os jobs chegarem a um estado terminal no RDS.
3. **quality_gate**: reprova o lote se alguma fonte ficar abaixo de 90% de sucesso.
4. **publish_manifest**: grava `manifests/<batch_id>.json` no S3 para os consumidores.

Falhas finais de qualquer task abrem incidente no monitor (`on_failure_callback`).
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta

import requests
from airflow.exceptions import AirflowFailException
from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.sdk import dag, task

MONITOR_URL = os.environ.get("MONITOR_URL", "http://monitor:8090")
DB_CONN_ID = "crawlerops_db"
MIN_SUCCESS_RATE = 0.9


def report_failure(context: dict) -> None:
    ti = context["task_instance"]
    exception = context.get("exception")
    payload = {
        "source": "pipeline",
        "rule": f"airflow_{ti.task_id}",
        "severity": "P2",
        "title": f"DAG {ti.dag_id}: task '{ti.task_id}' falhou",
        "details": {
            "dag_id": ti.dag_id,
            "run_id": ti.run_id,
            "try_number": ti.try_number,
            "error": str(exception)[:1000] if exception else None,
        },
    }
    try:
        requests.post(f"{MONITOR_URL}/api/incidents/report", json=payload, timeout=10)
    except requests.RequestException as exc:
        print(f"não foi possível reportar incidente: {exc}")


@dag(
    dag_id="capture_products",
    schedule=timedelta(minutes=3),
    start_date=datetime(2026, 1, 1, tzinfo=UTC),
    catchup=False,
    max_active_runs=1,
    default_args={
        "retries": 1,
        "retry_delay": timedelta(seconds=20),
        "on_failure_callback": report_failure,
    },
    tags=["captura", "sustentacao"],
    doc_md=__doc__,
)
def capture_products():
    @task
    def enqueue_batch() -> dict:
        from crawlerops.common.aws import aws_client
        from crawlerops.common.config import Settings
        from crawlerops.crawler.queue import SqsJobQueue
        from crawlerops.scheduler.batch import build_batch, new_batch_id

        settings = Settings.from_env()
        queue = SqsJobQueue(aws_client("sqs", settings), settings.sqs_queue_url, settings.sqs_dlq_url)
        batch_id = new_batch_id("airflow")
        sent = queue.send(build_batch(batch_id))
        print(f"lote {batch_id}: {sent} jobs enfileirados")
        return {"batch_id": batch_id, "expected": sent}

    @task.sensor(poke_interval=15, timeout=600, mode="reschedule")
    def wait_batch(batch: dict) -> bool:
        hook = PostgresHook(postgres_conn_id=DB_CONN_ID)
        (done,) = hook.get_first(
            "SELECT count(DISTINCT job_id) FROM capture_runs WHERE batch_id = %s AND terminal",
            parameters=(batch["batch_id"],),
        )
        print(f"{done}/{batch['expected']} jobs finalizados")
        return done >= batch["expected"]

    @task(retries=0)
    def quality_gate(batch: dict) -> dict:
        hook = PostgresHook(postgres_conn_id=DB_CONN_ID)
        rows = hook.get_records(
            """
            SELECT source,
                   count(DISTINCT job_id) FILTER (WHERE status = 'success') AS ok,
                   count(DISTINCT job_id)                                  AS total
            FROM capture_runs
            WHERE batch_id = %s AND terminal
            GROUP BY source
            """,
            parameters=(batch["batch_id"],),
        )
        summary = {source: {"ok": ok, "total": total, "rate": ok / total} for source, ok, total in rows}
        print(json.dumps(summary, indent=2))
        failing = {s: v for s, v in summary.items() if v["rate"] < MIN_SUCCESS_RATE}
        if failing:
            raise AirflowFailException(f"quality gate reprovado: {failing}")
        return summary

    @task
    def publish_manifest(batch: dict, summary: dict) -> str:
        from crawlerops.common.aws import aws_client
        from crawlerops.common.config import Settings

        hook = PostgresHook(postgres_conn_id=DB_CONN_ID)
        keys = [row[0] for row in hook.get_records(
            "SELECT s3_data_key FROM capture_runs WHERE batch_id = %s AND status = 'success'",
            parameters=(batch["batch_id"],),
        )]
        settings = Settings.from_env()
        key = f"manifests/{batch['batch_id']}.json"
        aws_client("s3", settings).put_object(
            Bucket=settings.s3_bucket,
            Key=key,
            Body=json.dumps({"batch_id": batch["batch_id"], "summary": summary, "files": keys}).encode(),
            ContentType="application/json",
        )
        return key

    batch = enqueue_batch()
    summary = quality_gate(batch)
    wait_batch(batch) >> summary
    publish_manifest(batch, summary)


capture_products()
