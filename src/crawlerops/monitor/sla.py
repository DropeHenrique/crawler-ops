"""Política de SLA por severidade.

- P1 (crítico): captura parada ou dados desatualizados para o negócio.
- P2 (alto): degradação relevante ou falha que exige correção de código.
- P3 (médio): sintomas sem impacto imediato (latência, qualidade parcial, backlog).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum


class Severity(StrEnum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"

    @property
    def rank(self) -> int:
        return {"P1": 3, "P2": 2, "P3": 1}[self.value]


@dataclass(frozen=True)
class SlaTarget:
    response: timedelta
    resolution: timedelta


SLA_POLICY: dict[Severity, SlaTarget] = {
    Severity.P1: SlaTarget(response=timedelta(minutes=15), resolution=timedelta(hours=2)),
    Severity.P2: SlaTarget(response=timedelta(minutes=30), resolution=timedelta(hours=8)),
    Severity.P3: SlaTarget(response=timedelta(hours=4), resolution=timedelta(hours=48)),
}

AT_RISK_FRACTION = 0.75


def due_dates(severity: Severity | str, opened_at: datetime) -> tuple[datetime, datetime]:
    target = SLA_POLICY[Severity(severity)]
    return opened_at + target.response, opened_at + target.resolution


def sla_snapshot(incident: dict, now: datetime) -> dict:
    """Situação do SLA de resposta (ack) e de resolução de um incidente."""
    opened = incident["opened_at"]
    response_due = incident["response_due_at"]
    resolution_due = incident["resolution_due_at"]
    acked = incident.get("acknowledged_at") or incident.get("resolved_at")
    resolved = incident.get("resolved_at")

    if acked:
        response = "met" if acked <= response_due else "late"
    else:
        response = "breached" if now > response_due else "pending"

    remaining = None
    if resolved:
        resolution = "met" if resolved <= resolution_due else "late"
    else:
        remaining = int((resolution_due - now).total_seconds())
        total = (resolution_due - opened).total_seconds() or 1
        elapsed_fraction = (now - opened).total_seconds() / total
        if now > resolution_due:
            resolution = "breached"
        elif elapsed_fraction >= AT_RISK_FRACTION:
            resolution = "at_risk"
        else:
            resolution = "on_track"

    return {"response": response, "resolution": resolution, "resolution_remaining_s": remaining}
