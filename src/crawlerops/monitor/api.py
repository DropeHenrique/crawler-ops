from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from prometheus_client import make_asgi_app
from pydantic import BaseModel, Field

from crawlerops.common.aws import aws_client
from crawlerops.common.config import Settings
from crawlerops.common.db import Database
from crawlerops.common.logging import configure_logging
from crawlerops.crawler.queue import SqsJobQueue
from crawlerops.monitor.evaluator import Evaluator
from crawlerops.monitor.notifier import CompositeNotifier, LogNotifier, Notifier, WebhookNotifier
from crawlerops.monitor.repository import IncidentRepository
from crawlerops.monitor.rules import Finding
from crawlerops.monitor.service import (
    IncidentNotFoundError,
    IncidentService,
    InvalidTransitionError,
)
from crawlerops.monitor.sla import SLA_POLICY, Severity, sla_snapshot
from crawlerops.monitor.stats import StatsRepository

logger = logging.getLogger("crawlerops.monitor")
STATIC_DIR = Path(__file__).parent / "static"


@dataclass
class Components:
    settings: Settings
    db: Database
    queue: SqsJobQueue
    stats: StatsRepository
    incident_repo: IncidentRepository
    incidents: IncidentService
    evaluator: Evaluator


def build_components(settings: Settings) -> Components:
    db = Database(settings.database_url)
    queue = SqsJobQueue(aws_client("sqs", settings), settings.sqs_queue_url, settings.sqs_dlq_url)
    notifiers: list[Notifier] = [LogNotifier()]
    if settings.alert_webhook_url:
        notifiers.append(WebhookNotifier(settings.alert_webhook_url))
    incident_repo = IncidentRepository(db)
    incidents = IncidentService(incident_repo, CompositeNotifier(*notifiers))
    stats = StatsRepository(db)
    evaluator = Evaluator(
        stats, queue, incidents, incident_repo,
        window_minutes=settings.monitor_window_minutes,
        interval_seconds=settings.evaluation_interval_seconds,
    )
    return Components(settings, db, queue, stats, incident_repo, incidents, evaluator)


class AckRequest(BaseModel):
    author: str = Field(min_length=2)
    note: str | None = None


class ResolveRequest(BaseModel):
    author: str = Field(min_length=2)
    notes: str = Field(min_length=10, description="Causa raiz e ação tomada (documentação).")


class NoteRequest(BaseModel):
    author: str = Field(min_length=2)
    message: str = Field(min_length=3)


class ReportRequest(BaseModel):
    source: str
    rule: str
    severity: Severity
    title: str
    details: dict = Field(default_factory=dict)


class RedriveRequest(BaseModel):
    limit: int = Field(default=100, ge=1, le=1000)


class ChaosRequest(BaseModel):
    source: Literal["alpha", "beta", "all"] = "all"
    mode: str
    probability: float = Field(default=1.0, ge=0, le=1)


def _with_sla(incident: dict, now: datetime) -> dict:
    return {**incident, "sla": sla_snapshot(incident, now)}


def create_app(components: Components | None = None) -> FastAPI:
    state: dict[str, Components] = {}

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if components is None:
            settings = Settings.from_env()
            configure_logging(settings.log_level)
            state["c"] = build_components(settings)
            state["c"].evaluator.start()
        else:
            state["c"] = components
        yield
        state["c"].evaluator.stop()

    app = FastAPI(title="CrawlerOps Monitor", version="0.1.0", lifespan=lifespan)
    app.mount("/metrics", make_asgi_app())

    def c() -> Components:
        return state["c"]

    def incident_or_404(incident_id: int) -> dict:
        incident = c().incident_repo.get(incident_id)
        if incident is None:
            raise HTTPException(404, "incidente não encontrado")
        return incident

    @app.get("/", include_in_schema=False)
    def dashboard() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/health")
    def health() -> dict:
        db_ok = c().db.ping()
        return {
            "status": "ok" if db_ok else "degraded",
            "database": db_ok,
            "last_evaluation": c().evaluator.last_run,
        }

    @app.get("/api/overview")
    def overview() -> dict:
        now = datetime.now(UTC)
        active = c().incident_repo.list_active()
        sources = []
        for s in c().stats.collect(c().settings.monitor_window_minutes):
            source_incidents = [i for i in active if i["source"] == s.source]
            worst = min((i["severity"] for i in source_incidents), default=None)
            sources.append({
                "source": s.source,
                "health": worst or "ok",
                "total": s.total,
                "success_rate": s.success_rate,
                "items": s.items,
                "invalid_items": s.invalid_items,
                "p95_success_ms": s.p95_success_ms,
                "errors": s.errors,
                "last_success_at": s.last_success_at,
                "freshness_s": int((now - s.last_success_at).total_seconds()) if s.last_success_at else None,
            })
        try:
            queues = {"main": c().queue.depth(), "dlq": c().queue.depth(dlq=True)}
        except Exception:
            queues = None
        return {
            "now": now,
            "window_minutes": c().settings.monitor_window_minutes,
            "sources": sources,
            "queues": queues,
            "incidents": {sev: sum(1 for i in active if i["severity"] == sev) for sev in ("P1", "P2", "P3")},
            "sla_policy": {
                sev.value: {"response_min": t.response.total_seconds() / 60,
                            "resolution_h": t.resolution.total_seconds() / 3600}
                for sev, t in SLA_POLICY.items()
            },
            "last_evaluation": c().evaluator.last_run,
        }

    @app.get("/api/incidents")
    def list_incidents(
        status: Literal["active", "resolved", "all"] = "active",
        limit: int = Query(50, ge=1, le=500),
    ) -> list[dict]:
        now = datetime.now(UTC)
        return [_with_sla(i, now) for i in c().incident_repo.list_incidents(status, limit)]

    @app.get("/api/incidents/{incident_id}")
    def get_incident(incident_id: int) -> dict:
        incident = incident_or_404(incident_id)
        return {**_with_sla(incident, datetime.now(UTC)), "events": c().incident_repo.events(incident_id)}

    @app.post("/api/incidents/report", status_code=201)
    def report_incident(body: ReportRequest) -> dict:
        finding = Finding(body.rule, body.source, body.severity, body.title, body.details,
                          auto_resolve=False)
        incident, action = c().incidents.report(finding)
        return {"action": action, "incident": incident}

    def _transition(fn: Callable[..., Any], *args: Any) -> Any:
        try:
            return fn(*args)
        except IncidentNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except InvalidTransitionError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/incidents/{incident_id}/ack")
    def ack_incident(incident_id: int, body: AckRequest) -> dict:
        return _transition(c().incidents.acknowledge, incident_id, body.author, body.note)

    @app.post("/api/incidents/{incident_id}/resolve")
    def resolve_incident(incident_id: int, body: ResolveRequest) -> dict:
        return _transition(c().incidents.resolve, incident_id, body.author, body.notes)

    @app.post("/api/incidents/{incident_id}/notes", status_code=201)
    def add_note(incident_id: int, body: NoteRequest) -> dict:
        _transition(c().incidents.add_note, incident_id, body.author, body.message)
        return {"ok": True}

    @app.get("/api/runs")
    def recent_runs(limit: int = Query(30, ge=1, le=500), source: str | None = None) -> list[dict]:
        return c().stats.recent_runs(limit, source)

    @app.get("/api/dlq")
    def dlq() -> dict:
        return {"depth": c().queue.depth(dlq=True), "sample": c().queue.peek_dlq(10)}

    @app.post("/api/dlq/redrive")
    def redrive(body: RedriveRequest) -> dict:
        moved = c().queue.redrive(body.limit)
        logger.warning("redrive da DLQ executado", extra={"moved": moved})
        return {"moved": moved}

    @app.post("/api/evaluate")
    def evaluate_now() -> dict:
        return c().evaluator.run_once()

    def _chaos(method: str, path: str, payload: dict | None = None) -> dict:
        try:
            response = httpx.request(
                method, f"{c().settings.target_base_url}{path}", json=payload, timeout=5
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            raise HTTPException(502, f"site-alvo indisponível: {exc}") from exc

    @app.get("/api/chaos")
    def get_chaos() -> dict:
        return _chaos("GET", "/admin/chaos")

    @app.post("/api/chaos")
    def set_chaos(body: ChaosRequest) -> dict:
        logger.warning("chaos alterado", extra=body.model_dump())
        return _chaos("POST", "/admin/chaos", body.model_dump())

    @app.post("/api/chaos/reset")
    def reset_chaos() -> dict:
        return _chaos("POST", "/admin/chaos/reset")

    return app


app = create_app()
