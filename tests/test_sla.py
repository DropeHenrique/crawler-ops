from datetime import UTC, datetime, timedelta

from crawlerops.monitor.sla import Severity, due_dates, sla_snapshot

OPENED = datetime(2026, 10, 3, 3, 0, tzinfo=UTC)


def _incident(severity="P1", **kwargs) -> dict:
    response_due, resolution_due = due_dates(severity, OPENED)
    return {"opened_at": OPENED, "response_due_at": response_due, "resolution_due_at": resolution_due,
            "acknowledged_at": None, "resolved_at": None, **kwargs}


def test_due_dates_per_severity():
    assert due_dates(Severity.P1, OPENED) == (OPENED + timedelta(minutes=15), OPENED + timedelta(hours=2))
    assert due_dates("P2", OPENED) == (OPENED + timedelta(minutes=30), OPENED + timedelta(hours=8))
    assert due_dates("P3", OPENED)[1] == OPENED + timedelta(hours=48)


def test_fresh_incident_is_pending_and_on_track():
    snap = sla_snapshot(_incident(), OPENED + timedelta(minutes=5))

    assert snap["response"] == "pending"
    assert snap["resolution"] == "on_track"
    assert snap["resolution_remaining_s"] == int(timedelta(minutes=115).total_seconds())


def test_response_breached_without_ack():
    assert sla_snapshot(_incident(), OPENED + timedelta(minutes=16))["response"] == "breached"


def test_late_ack_is_flagged():
    incident = _incident(acknowledged_at=OPENED + timedelta(minutes=20))

    assert sla_snapshot(incident, OPENED + timedelta(minutes=30))["response"] == "late"


def test_resolution_at_risk_after_75_percent_of_window():
    assert sla_snapshot(_incident(), OPENED + timedelta(minutes=95))["resolution"] == "at_risk"


def test_resolution_breached():
    assert sla_snapshot(_incident(), OPENED + timedelta(hours=3))["resolution"] == "breached"


def test_resolved_in_time_counts_as_met_for_both():
    incident = _incident(resolved_at=OPENED + timedelta(minutes=10))

    snap = sla_snapshot(incident, OPENED + timedelta(hours=5))

    assert snap == {"response": "met", "resolution": "met", "resolution_remaining_s": None}


def test_severity_rank_orders_p1_highest():
    assert Severity.P1.rank > Severity.P2.rank > Severity.P3.rank
