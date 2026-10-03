from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import count

import pytest

from crawlerops.monitor.rules import Finding
from crawlerops.monitor.service import IncidentService, InvalidTransitionError
from crawlerops.monitor.sla import Severity


class MemoryIncidentRepo:
    def __init__(self) -> None:
        self.items: dict[int, dict] = {}
        self.events: list[dict] = []
        self._ids = count(1)

    def get(self, incident_id):
        return self.items.get(incident_id)

    def get_active(self, fingerprint):
        return next((i for i in self.items.values()
                     if i["fingerprint"] == fingerprint and i["status"] != "resolved"), None)

    def list_active(self):
        return [i for i in self.items.values() if i["status"] != "resolved"]

    def create(self, finding, opened_at, response_due, resolution_due):
        incident = {
            "id": next(self._ids), "fingerprint": finding.fingerprint, "source": finding.source,
            "rule": finding.rule, "severity": finding.severity.value, "status": "open",
            "title": finding.title, "details": finding.details, "auto_resolve": finding.auto_resolve,
            "occurrences": 1, "opened_at": opened_at, "last_seen_at": opened_at,
            "acknowledged_at": None, "resolved_at": None, "response_due_at": response_due,
            "resolution_due_at": resolution_due, "resolved_by": None, "resolution_notes": None,
        }
        self.items[incident["id"]] = incident
        return incident

    def update(self, incident_id, **fields):
        self.items[incident_id].update(fields)
        return self.items[incident_id]

    def touch(self, incident_id, title, details, seen_at):
        incident = self.items[incident_id]
        incident.update(title=title, details=details, last_seen_at=seen_at,
                        occurrences=incident["occurrences"] + 1)
        return incident

    def add_event(self, incident_id, kind, message, author="system"):
        self.events.append({"incident_id": incident_id, "kind": kind, "message": message, "author": author})


class RecordingNotifier:
    def __init__(self) -> None:
        self.events: list[tuple[str, int]] = []

    def notify(self, event, incident):
        self.events.append((event, incident["id"]))


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 3, 3, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def ctx():
    repo, notifier, clock = MemoryIncidentRepo(), RecordingNotifier(), Clock()
    return IncidentService(repo, notifier, clock), repo, notifier, clock


def _finding(severity=Severity.P2, rule="capture_health", source="alpha", **kw) -> Finding:
    return Finding(rule, source, severity, f"{rule} {severity}", {"x": 1}, **kw)


def test_new_finding_opens_incident_with_sla_and_notifies(ctx):
    service, repo, notifier, clock = ctx

    incident, action = service.report(_finding(Severity.P1))

    assert action == "opened"
    assert incident["resolution_due_at"] == clock.now + timedelta(hours=2)
    assert notifier.events == [("opened", 1)]
    assert repo.events[0]["kind"] == "opened"


def test_repeated_finding_is_deduplicated(ctx):
    service, repo, notifier, _ = ctx
    service.report(_finding())

    incident, action = service.report(_finding())

    assert action == "updated"
    assert incident["occurrences"] == 2
    assert len(repo.items) == 1
    assert len(notifier.events) == 1


def test_higher_severity_escalates_keeping_original_open_time(ctx):
    service, _, notifier, clock = ctx
    opened, _ = service.report(_finding(Severity.P2))
    clock.now += timedelta(minutes=10)

    incident, action = service.report(_finding(Severity.P1))

    assert action == "escalated"
    assert incident["severity"] == "P1"
    assert incident["resolution_due_at"] == opened["opened_at"] + timedelta(hours=2)
    assert notifier.events[-1] == ("escalated", incident["id"])


def test_lower_severity_does_not_downgrade(ctx):
    service, _, _, _ = ctx
    service.report(_finding(Severity.P1))

    incident, action = service.report(_finding(Severity.P3))

    assert (action, incident["severity"]) == ("updated", "P1")


def test_sync_auto_resolves_cleared_conditions_only(ctx):
    service, repo, _, _ = ctx
    service.report(_finding(rule="capture_health"))
    service.report(_finding(rule="dead_letter_timeout", auto_resolve=False))

    summary = service.sync([])

    assert summary["auto_resolved"] == 1
    statuses = {i["rule"]: i["status"] for i in repo.items.values()}
    assert statuses == {"capture_health": "resolved", "dead_letter_timeout": "open"}
    assert repo.items[1]["resolved_by"] == "auto"


def test_resolved_incident_reopens_as_new_when_condition_returns(ctx):
    service, repo, _, _ = ctx
    service.report(_finding())
    service.sync([])

    _, action = service.report(_finding())

    assert action == "opened"
    assert len(repo.items) == 2


def test_acknowledge_and_resolve_flow(ctx):
    service, repo, notifier, clock = ctx
    incident, _ = service.report(_finding())
    clock.now += timedelta(minutes=5)

    acked = service.acknowledge(incident["id"], "pedro", "investigando")
    resolved = service.resolve(incident["id"], "pedro", "Seletor atualizado e DLQ reprocessada")

    assert acked["acknowledged_at"] == clock.now
    assert resolved["status"] == "resolved"
    assert resolved["resolved_by"] == "pedro"
    assert [e["kind"] for e in repo.events] == ["opened", "acknowledged", "resolved"]
    assert [e for e, _ in notifier.events] == ["opened", "acknowledged", "resolved"]


def test_invalid_transitions(ctx):
    service, _, _, _ = ctx
    incident, _ = service.report(_finding())
    service.acknowledge(incident["id"], "pedro")

    with pytest.raises(InvalidTransitionError):
        service.acknowledge(incident["id"], "pedro")

    service.resolve(incident["id"], "pedro", "resolvido manualmente")
    with pytest.raises(InvalidTransitionError):
        service.resolve(incident["id"], "pedro", "de novo")
