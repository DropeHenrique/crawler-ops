from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime

import psycopg

from crawlerops.monitor.notifier import Notifier
from crawlerops.monitor.repository import IncidentRepository
from crawlerops.monitor.rules import Finding
from crawlerops.monitor.sla import Severity, due_dates

logger = logging.getLogger("crawlerops.incidents")


class IncidentNotFoundError(Exception):
    pass


class InvalidTransitionError(Exception):
    pass


class IncidentService:
    """Ciclo de vida: open → acknowledged → resolved.

    - Achados repetidos atualizam o incidente ativo (deduplicação por fingerprint).
    - Severidade só sobe automaticamente (P3 → P2 → P1); rebaixar é decisão humana.
    - Incidentes de regras métricas são resolvidos sozinhos quando a condição some.
    """

    def __init__(
        self,
        repository: IncidentRepository,
        notifier: Notifier,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repo = repository
        self._notifier = notifier
        self._clock = clock

    def report(self, finding: Finding) -> tuple[dict, str]:
        now = self._clock()
        active = self._repo.get_active(finding.fingerprint)
        if active is None:
            response_due, resolution_due = due_dates(finding.severity, now)
            try:
                incident = self._repo.create(finding, now, response_due, resolution_due)
            except psycopg.errors.UniqueViolation:
                return self.report(finding)
            self._repo.add_event(incident["id"], "opened", finding.title)
            self._notifier.notify("opened", incident)
            return incident, "opened"

        if finding.severity.rank > Severity(active["severity"]).rank:
            response_due, resolution_due = due_dates(finding.severity, active["opened_at"])
            incident = self._repo.update(
                active["id"], severity=finding.severity.value, title=finding.title,
                details=finding.details, last_seen_at=now,
                response_due_at=response_due, resolution_due_at=resolution_due,
            )
            self._repo.add_event(
                incident["id"], "escalated",
                f"Severidade elevada de {active['severity']} para {finding.severity}: {finding.title}",
            )
            self._notifier.notify("escalated", incident)
            return incident, "escalated"

        return self._repo.touch(active["id"], finding.title, finding.details, now), "updated"

    def sync(self, findings: list[Finding]) -> dict[str, int]:
        """Aplica os achados de um ciclo de avaliação e auto-resolve o que normalizou."""
        summary = {"opened": 0, "escalated": 0, "updated": 0, "auto_resolved": 0}
        current = {f.fingerprint for f in findings}
        for finding in findings:
            _, action = self.report(finding)
            summary[action] += 1

        for incident in self._repo.list_active():
            if incident["auto_resolve"] and incident["fingerprint"] not in current:
                self._resolve(incident, author="auto",
                              notes="Condição normalizada: métrica voltou ao patamar esperado.")
                summary["auto_resolved"] += 1
        return summary

    def acknowledge(self, incident_id: int, author: str, note: str | None = None) -> dict:
        incident = self._get(incident_id)
        if incident["status"] != "open":
            raise InvalidTransitionError(f"incidente está '{incident['status']}', não 'open'")
        updated = self._repo.update(incident_id, status="acknowledged", acknowledged_at=self._clock())
        self._repo.add_event(incident_id, "acknowledged", note or "Incidente assumido.", author)
        self._notifier.notify("acknowledged", updated)
        return updated

    def resolve(self, incident_id: int, author: str, notes: str) -> dict:
        incident = self._get(incident_id)
        if incident["status"] == "resolved":
            raise InvalidTransitionError("incidente já está resolvido")
        return self._resolve(incident, author=author, notes=notes)

    def add_note(self, incident_id: int, author: str, message: str) -> None:
        self._get(incident_id)
        self._repo.add_event(incident_id, "note", message, author)

    def _resolve(self, incident: dict, *, author: str, notes: str) -> dict:
        updated = self._repo.update(
            incident["id"], status="resolved", resolved_at=self._clock(),
            resolved_by=author, resolution_notes=notes,
        )
        self._repo.add_event(incident["id"], "resolved", notes, author)
        self._notifier.notify("resolved", updated)
        return updated

    def _get(self, incident_id: int) -> dict:
        incident = self._repo.get(incident_id)
        if incident is None:
            raise IncidentNotFoundError(f"incidente {incident_id} não encontrado")
        return incident
