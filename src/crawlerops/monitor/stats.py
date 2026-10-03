from __future__ import annotations

from crawlerops.common.db import Database
from crawlerops.common.models import SOURCES
from crawlerops.monitor.rules import SourceStats

_WINDOW_SQL = """
SELECT source,
       count(*)                                        AS total,
       count(*) FILTER (WHERE status = 'success')      AS success,
       count(*) FILTER (WHERE status = 'failed')       AS failed,
       coalesce(sum(items_count), 0)                   AS items,
       coalesce(sum(invalid_items), 0)                 AS invalid_items,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms)
           FILTER (WHERE status = 'success')           AS p95_success_ms
FROM capture_runs
WHERE finished_at > now() - make_interval(mins => %(window)s)
GROUP BY source
"""

_ERRORS_SQL = """
SELECT source, error_type, count(*) AS n,
       (array_agg(s3_raw_key ORDER BY finished_at DESC)
            FILTER (WHERE s3_raw_key IS NOT NULL))[1] AS sample_key
FROM capture_runs
WHERE status = 'failed' AND finished_at > now() - make_interval(mins => %(window)s)
GROUP BY source, error_type
"""

_FRESHNESS_SQL = """
SELECT source,
       max(finished_at) FILTER (WHERE status = 'success') AS last_success_at,
       max(finished_at)                                   AS last_run_at
FROM capture_runs
GROUP BY source
"""


class StatsRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def collect(self, window_minutes: int) -> list[SourceStats]:
        params = {"window": window_minutes}
        with self._db.connection() as conn:
            window = {r["source"]: r for r in conn.execute(_WINDOW_SQL, params)}
            errors = conn.execute(_ERRORS_SQL, params).fetchall()
            freshness = {r["source"]: r for r in conn.execute(_FRESHNESS_SQL)}

        sources = sorted(set(SOURCES) | set(window) | set(freshness))
        result = []
        for source in sources:
            w = window.get(source, {})
            f = freshness.get(source, {})
            source_errors = [e for e in errors if e["source"] == source]
            layout_sample = next(
                (e["sample_key"] for e in source_errors
                 if e["error_type"] in ("layout_changed", "data_validation") and e["sample_key"]),
                None,
            )
            result.append(SourceStats(
                source=source,
                total=w.get("total", 0),
                success=w.get("success", 0),
                failed=w.get("failed", 0),
                items=int(w.get("items", 0)),
                invalid_items=int(w.get("invalid_items", 0)),
                p95_success_ms=w.get("p95_success_ms"),
                errors={e["error_type"]: e["n"] for e in source_errors},
                last_success_at=f.get("last_success_at"),
                last_run_at=f.get("last_run_at"),
                layout_sample_key=layout_sample,
            ))
        return result

    def recent_runs(self, limit: int = 30, source: str | None = None) -> list[dict]:
        query = """
            SELECT id, job_id, batch_id, source, target_url, status, terminal, error_type,
                   error_message, attempt, items_count, invalid_items, duration_ms, http_status,
                   s3_raw_key, s3_data_key, worker_id, finished_at
            FROM capture_runs
            WHERE (%(source)s::text IS NULL OR source = %(source)s)
            ORDER BY finished_at DESC
            LIMIT %(limit)s
        """
        with self._db.connection() as conn:
            return conn.execute(query, {"source": source, "limit": limit}).fetchall()
