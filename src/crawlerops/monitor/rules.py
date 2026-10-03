"""Regras de detecção de incidentes a partir das estatísticas de captura.

Cada regra é uma classe pequena e independente (fácil de testar e de adicionar novas).
O ``fingerprint`` (regra + fonte) deduplica alertas: enquanto o problema persistir,
o mesmo incidente é atualizado em vez de abrir um novo.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from crawlerops.monitor.sla import Severity


@dataclass(frozen=True)
class SourceStats:
    source: str
    total: int = 0
    success: int = 0
    failed: int = 0
    items: int = 0
    invalid_items: int = 0
    p95_success_ms: float | None = None
    errors: dict[str, int] = field(default_factory=dict)
    last_success_at: datetime | None = None
    last_run_at: datetime | None = None
    layout_sample_key: str | None = None

    @property
    def success_rate(self) -> float | None:
        return self.success / self.total if self.total else None

    @property
    def invalid_ratio(self) -> float:
        seen = self.items + self.invalid_items
        return self.invalid_items / seen if seen else 0.0


@dataclass(frozen=True)
class Thresholds:
    min_runs: int = 4
    unavailable_success_rate: float = 0.5
    degraded_success_rate: float = 0.9
    p95_latency_ms: float = 3000
    invalid_ratio: float = 0.05
    stale_minutes: int = 10
    rate_limited_min: int = 3


@dataclass(frozen=True)
class Finding:
    rule: str
    source: str
    severity: Severity
    title: str
    details: dict = field(default_factory=dict)
    auto_resolve: bool = True

    @property
    def fingerprint(self) -> str:
        return f"{self.rule}:{self.source}"


class Rule(ABC):
    name: str

    def __init__(self, thresholds: Thresholds) -> None:
        self.t = thresholds

    @abstractmethod
    def evaluate(self, stats: SourceStats, now: datetime) -> Finding | None: ...


class CaptureHealthRule(Rule):
    """Taxa de sucesso na janela: < 50% é P1 (indisponível), < 90% é P2 (degradado)."""

    name = "capture_health"

    def evaluate(self, stats: SourceStats, now: datetime) -> Finding | None:
        rate = stats.success_rate
        if rate is None or stats.total < self.t.min_runs:
            return None
        details = {
            "success_rate": round(rate, 3), "total": stats.total,
            "failed": stats.failed, "errors": stats.errors,
        }
        if rate < self.t.unavailable_success_rate:
            return Finding(self.name, stats.source, Severity.P1,
                           f"Captura indisponível em '{stats.source}' ({rate:.0%} de sucesso)", details)
        if rate < self.t.degraded_success_rate:
            return Finding(self.name, stats.source, Severity.P2,
                           f"Captura degradada em '{stats.source}' ({rate:.0%} de sucesso)", details)
        return None


class StaleDataRule(Rule):
    """Freshness: sem captura bem-sucedida há mais de N minutos = dado velho para o negócio."""

    name = "stale_data"

    def evaluate(self, stats: SourceStats, now: datetime) -> Finding | None:
        if stats.last_success_at is None:
            return None
        age = now - stats.last_success_at
        if age <= timedelta(minutes=self.t.stale_minutes):
            return None
        minutes = int(age.total_seconds() // 60)
        return Finding(
            self.name, stats.source, Severity.P1,
            f"Dados de '{stats.source}' desatualizados há {minutes} min",
            {"last_success_at": stats.last_success_at.isoformat(), "age_minutes": minutes,
             "last_run_at": stats.last_run_at.isoformat() if stats.last_run_at else None},
        )


class LayoutChangedRule(Rule):
    """Parser não encontrou a estrutura esperada: exige correção de código (P2)."""

    name = "layout_changed"

    def evaluate(self, stats: SourceStats, now: datetime) -> Finding | None:
        count = stats.errors.get("layout_changed", 0) + stats.errors.get("data_validation", 0)
        if not count:
            return None
        return Finding(
            self.name, stats.source, Severity.P2,
            f"Possível mudança de layout em '{stats.source}' ({count} falhas de parsing)",
            {"parsing_failures": count, "raw_html_sample": stats.layout_sample_key},
        )


class RateLimitRule(Rule):
    name = "rate_limited"

    def evaluate(self, stats: SourceStats, now: datetime) -> Finding | None:
        count = stats.errors.get("rate_limited", 0)
        if count < self.t.rate_limited_min:
            return None
        return Finding(
            self.name, stats.source, Severity.P2,
            f"'{stats.source}' está limitando nossas requisições (HTTP 429 x{count})",
            {"rate_limited": count},
        )


class LatencyRule(Rule):
    name = "high_latency"

    def evaluate(self, stats: SourceStats, now: datetime) -> Finding | None:
        p95 = stats.p95_success_ms
        if p95 is None or stats.success < self.t.min_runs or p95 <= self.t.p95_latency_ms:
            return None
        return Finding(
            self.name, stats.source, Severity.P3,
            f"Latência alta em '{stats.source}' (p95 {p95 / 1000:.1f}s)",
            {"p95_ms": round(p95), "threshold_ms": self.t.p95_latency_ms},
        )


class DataQualityRule(Rule):
    name = "data_quality"

    def evaluate(self, stats: SourceStats, now: datetime) -> Finding | None:
        ratio = stats.invalid_ratio
        if ratio <= self.t.invalid_ratio:
            return None
        return Finding(
            self.name, stats.source, Severity.P3,
            f"Qualidade de dados baixa em '{stats.source}' ({ratio:.0%} itens inválidos)",
            {"invalid_ratio": round(ratio, 3), "invalid_items": stats.invalid_items,
             "valid_items": stats.items},
        )


RULES: tuple[type[Rule], ...] = (
    CaptureHealthRule, StaleDataRule, LayoutChangedRule, RateLimitRule, LatencyRule, DataQualityRule,
)


def evaluate_sources(
    all_stats: list[SourceStats], now: datetime, thresholds: Thresholds | None = None
) -> list[Finding]:
    rules = [rule(thresholds or Thresholds()) for rule in RULES]
    return [f for stats in all_stats for rule in rules if (f := rule.evaluate(stats, now))]


def evaluate_dlq(depth: int) -> list[Finding]:
    if depth <= 0:
        return []
    return [Finding(
        "dlq_backlog", "pipeline", Severity.P3,
        f"{depth} mensagem(ns) na DLQ aguardando tratativa",
        {"dlq_depth": depth},
    )]
