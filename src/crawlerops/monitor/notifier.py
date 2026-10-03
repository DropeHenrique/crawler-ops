from __future__ import annotations

import logging
from typing import Protocol

import httpx

logger = logging.getLogger("crawlerops.notifier")

_LABELS = {
    "opened": "ABERTO",
    "escalated": "ESCALADO",
    "acknowledged": "EM ATENDIMENTO",
    "resolved": "RESOLVIDO",
}


def format_message(event: str, incident: dict) -> str:
    label = _LABELS.get(event, event.upper())
    due = incident["resolution_due_at"].strftime("%H:%M UTC")
    text = f"[{incident['severity']}] {label} #{incident['id']} - {incident['title']}"
    if event in ("opened", "escalated"):
        text += f" | SLA de resolução até {due}"
    if event == "resolved" and incident.get("resolution_notes"):
        text += f" | {incident['resolution_notes']}"
    return text


class Notifier(Protocol):
    def notify(self, event: str, incident: dict) -> None: ...


class LogNotifier:
    def notify(self, event: str, incident: dict) -> None:
        level = logging.ERROR if incident["severity"] == "P1" and event != "resolved" else logging.WARNING
        logger.log(level, format_message(event, incident),
                   extra={"incident_id": incident["id"], "event": event})


class WebhookNotifier:
    """Compatível com webhooks do Slack/Teams/Discord (payload ``{"text": ...}``)."""

    def __init__(self, url: str, timeout: float = 5) -> None:
        self._url = url
        self._timeout = timeout

    def notify(self, event: str, incident: dict) -> None:
        try:
            httpx.post(self._url, json={"text": format_message(event, incident)}, timeout=self._timeout)
        except httpx.HTTPError:
            logger.exception("falha ao enviar webhook de alerta")


class CompositeNotifier:
    def __init__(self, *notifiers: Notifier) -> None:
        self._notifiers = notifiers

    def notify(self, event: str, incident: dict) -> None:
        for notifier in self._notifiers:
            notifier.notify(event, incident)
