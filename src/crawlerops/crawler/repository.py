from __future__ import annotations

from typing import Protocol

from crawlerops.common.db import Database
from crawlerops.crawler.models import CaptureRun


class RunRepository(Protocol):
    def record(self, run: CaptureRun) -> None: ...


class PostgresRunRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def record(self, run: CaptureRun) -> None:
        with self._db.connection() as conn:
            conn.execute(
                """
                INSERT INTO capture_runs (
                    job_id, batch_id, source, target_url, status, terminal, error_type,
                    error_message, attempt, items_count, invalid_items, duration_ms, http_status,
                    s3_raw_key, s3_data_key, worker_id, started_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    run.job.job_id, run.job.batch_id, run.job.source, run.target_url, run.status,
                    run.terminal, run.error_type, run.error_message, run.attempt, run.items_count,
                    run.invalid_items, run.duration_ms, run.http_status, run.s3_raw_key,
                    run.s3_data_key, run.worker_id, run.started_at,
                ),
            )
