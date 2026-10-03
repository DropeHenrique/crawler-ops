from datetime import UTC, datetime, timedelta

from crawlerops.monitor.rules import SourceStats, Thresholds, evaluate_dlq, evaluate_sources
from crawlerops.monitor.sla import Severity

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)


def _stats(**kwargs) -> SourceStats:
    defaults = {
        "source": "alpha", "total": 20, "success": 20, "failed": 0, "items": 400,
        "invalid_items": 0, "p95_success_ms": 300, "last_success_at": NOW - timedelta(minutes=1),
        "last_run_at": NOW,
    }
    return SourceStats(**{**defaults, **kwargs})


def _rules(findings) -> dict[str, Severity]:
    return {f.rule: f.severity for f in findings}


def test_healthy_source_has_no_findings():
    assert evaluate_sources([_stats()], NOW) == []


def test_success_rate_below_50_percent_is_p1():
    findings = evaluate_sources([_stats(success=6, failed=14, errors={"timeout": 14})], NOW)

    assert _rules(findings)["capture_health"] is Severity.P1


def test_success_rate_between_50_and_90_percent_is_p2():
    findings = evaluate_sources([_stats(success=15, failed=5, errors={"http_5xx": 5})], NOW)

    assert _rules(findings) == {"capture_health": Severity.P2}


def test_few_runs_do_not_trigger_health_rule():
    findings = evaluate_sources([_stats(total=2, success=0, failed=2)], NOW)

    assert "capture_health" not in _rules(findings)


def test_stale_data_is_p1():
    findings = evaluate_sources([_stats(last_success_at=NOW - timedelta(minutes=25))], NOW)

    stale = next(f for f in findings if f.rule == "stale_data")
    assert stale.severity is Severity.P1
    assert stale.details["age_minutes"] == 25


def test_layout_change_is_p2_with_raw_html_sample():
    findings = evaluate_sources(
        [_stats(success=10, failed=10, errors={"layout_changed": 10},
                layout_sample_key="raw/alpha/x.html")],
        NOW,
    )

    layout = next(f for f in findings if f.rule == "layout_changed")
    assert layout.severity is Severity.P2
    assert layout.details["raw_html_sample"] == "raw/alpha/x.html"


def test_rate_limit_needs_minimum_occurrences():
    assert "rate_limited" not in _rules(evaluate_sources([_stats(errors={"rate_limited": 2})], NOW))
    assert _rules(evaluate_sources([_stats(errors={"rate_limited": 3})], NOW))["rate_limited"] is Severity.P2


def test_high_latency_is_p3():
    findings = evaluate_sources([_stats(p95_success_ms=5200)], NOW)

    assert _rules(findings) == {"high_latency": Severity.P3}


def test_data_quality_is_p3():
    findings = evaluate_sources([_stats(items=340, invalid_items=60)], NOW)

    assert _rules(findings) == {"data_quality": Severity.P3}


def test_custom_thresholds_are_respected():
    findings = evaluate_sources([_stats(p95_success_ms=1500)], NOW, Thresholds(p95_latency_ms=1000))

    assert "high_latency" in _rules(findings)


def test_fingerprint_combines_rule_and_source():
    finding = evaluate_sources([_stats(source="beta", p95_success_ms=9000)], NOW)[0]

    assert finding.fingerprint == "high_latency:beta"


def test_dlq_backlog():
    assert evaluate_dlq(0) == []
    finding = evaluate_dlq(7)[0]
    assert (finding.rule, finding.severity, finding.details["dlq_depth"]) == ("dlq_backlog", Severity.P3, 7)
