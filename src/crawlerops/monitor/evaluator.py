from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime

from crawlerops.crawler.queue import SqsJobQueue
from crawlerops.monitor import metrics
from crawlerops.monitor.repository import IncidentRepository
from crawlerops.monitor.rules import SourceStats, Thresholds, evaluate_dlq, evaluate_sources
from crawlerops.monitor.service import IncidentService
from crawlerops.monitor.sla import sla_snapshot
from crawlerops.monitor.stats import StatsRepository

logger = logging.getLogger("crawlerops.evaluator")


class Evaluator:
    """Loop de monitoramento: coleta métricas, aplica regras e sincroniza incidentes."""

    def __init__(
        self,
        stats: StatsRepository,
        queue: SqsJobQueue,
        incidents: IncidentService,
        incident_repo: IncidentRepository,
        *,
        window_minutes: int,
        interval_seconds: int,
        thresholds: Thresholds | None = None,
    ) -> None:
        self._stats = stats
        self._queue = queue
        self._incidents = incidents
        self._incident_repo = incident_repo
        self._window = window_minutes
        self._interval = interval_seconds
        self._thresholds = thresholds or Thresholds()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.last_run: dict = {}

    def run_once(self) -> dict:
        with self._lock:
            now = datetime.now(UTC)
            source_stats = self._stats.collect(self._window)
            dlq_depth = self._queue_depths()
            findings = evaluate_sources(source_stats, now, self._thresholds)
            findings += evaluate_dlq(dlq_depth)
            summary = self._incidents.sync(findings)
            self._export_metrics(source_stats, now)
            self.last_run = {"at": now.isoformat(), "findings": len(findings), **summary}
            if any(summary[k] for k in ("opened", "escalated", "auto_resolved")):
                logger.info("avaliação concluída", extra=self.last_run)
            return self.last_run

    def start(self) -> None:
        threading.Thread(target=self._loop, name="evaluator", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:
                logger.exception("falha no ciclo de avaliação")
            self._stop.wait(self._interval)

    def _queue_depths(self) -> int:
        try:
            main = self._queue.depth()["visible"]
            dlq = self._queue.depth(dlq=True)["visible"]
        except Exception:
            logger.exception("não foi possível ler a profundidade das filas")
            return 0
        metrics.QUEUE_DEPTH.labels("capture-jobs").set(main)
        metrics.QUEUE_DEPTH.labels("capture-jobs-dlq").set(dlq)
        return dlq

    def _export_metrics(self, source_stats: list[SourceStats], now: datetime) -> None:
        for s in source_stats:
            if s.success_rate is not None:
                metrics.SOURCE_SUCCESS_RATE.labels(s.source).set(s.success_rate)
            if s.last_success_at:
                metrics.DATA_FRESHNESS.labels(s.source).set((now - s.last_success_at).total_seconds())

        active = self._incident_repo.list_active()
        for severity in ("P1", "P2", "P3"):
            metrics.OPEN_INCIDENTS.labels(severity).set(
                sum(1 for i in active if i["severity"] == severity)
            )
        metrics.SLA_BREACHED.set(
            sum(1 for i in active if sla_snapshot(i, now)["resolution"] == "breached")
        )
        metrics.LAST_EVALUATION.set(now.timestamp())
