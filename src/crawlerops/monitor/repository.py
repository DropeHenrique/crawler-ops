from __future__ import annotations

from datetime import datetime
from typing import Any

from psycopg.types.json import Jsonb

from crawlerops.common.db import Database
from crawlerops.monitor.rules import Finding


class IncidentRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, incident_id: int) -> dict | None:
        with self._db.connection() as conn:
            return conn.execute("SELECT * FROM incidents WHERE id = %s", (incident_id,)).fetchone()

    def get_active(self, fingerprint: str) -> dict | None:
        with self._db.connection() as conn:
            return conn.execute(
                "SELECT * FROM incidents WHERE fingerprint = %s AND status <> 'resolved'",
                (fingerprint,),
            ).fetchone()

    def list_active(self) -> list[dict]:
        return self.list_incidents(status="active", limit=500)

    def list_incidents(self, status: str = "active", limit: int = 50) -> list[dict]:
        where = {
            "active": "status <> 'resolved'",
            "resolved": "status = 'resolved'",
            "all": "TRUE",
        }[status]
        with self._db.connection() as conn:
            return conn.execute(
                f"""SELECT * FROM incidents WHERE {where}
                    ORDER BY (status = 'resolved'),
                             CASE severity WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END,
                             opened_at DESC
                    LIMIT %s""",
                (limit,),
            ).fetchall()

    def events(self, incident_id: int) -> list[dict]:
        with self._db.connection() as conn:
            return conn.execute(
                "SELECT * FROM incident_events WHERE incident_id = %s ORDER BY created_at, id",
                (incident_id,),
            ).fetchall()

    def create(
        self, finding: Finding, opened_at: datetime, response_due: datetime, resolution_due: datetime
    ) -> dict:
        with self._db.connection() as conn:
            return conn.execute(
                """INSERT INTO incidents (fingerprint, source, rule, severity, status, title, details,
                       auto_resolve, opened_at, last_seen_at, response_due_at, resolution_due_at)
                   VALUES (%s, %s, %s, %s, 'open', %s, %s, %s, %s, %s, %s, %s)
                   RETURNING *""",
                (finding.fingerprint, finding.source, finding.rule, finding.severity.value,
                 finding.title, Jsonb(finding.details), finding.auto_resolve, opened_at, opened_at,
                 response_due, resolution_due),
            ).fetchone()

    def update(self, incident_id: int, **fields: Any) -> dict:
        if "details" in fields:
            fields["details"] = Jsonb(fields["details"])
        assignments = ", ".join(f"{name} = %({name})s" for name in fields)
        with self._db.connection() as conn:
            return conn.execute(
                f"UPDATE incidents SET {assignments} WHERE id = %(id)s RETURNING *",
                {**fields, "id": incident_id},
            ).fetchone()

    def touch(self, incident_id: int, title: str, details: dict, seen_at: datetime) -> dict:
        with self._db.connection() as conn:
            return conn.execute(
                """UPDATE incidents
                   SET occurrences = occurrences + 1, last_seen_at = %s, title = %s, details = %s
                   WHERE id = %s RETURNING *""",
                (seen_at, title, Jsonb(details), incident_id),
            ).fetchone()

    def add_event(self, incident_id: int, kind: str, message: str, author: str = "system") -> None:
        with self._db.connection() as conn:
            conn.execute(
                "INSERT INTO incident_events (incident_id, kind, message, author) VALUES (%s, %s, %s, %s)",
                (incident_id, kind, message, author),
            )
