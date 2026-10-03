"""Lambda ``failure-alert``: SNS (falha definitiva de captura) → incidente no monitor.

Sem dependências externas (só stdlib) para manter o pacote de deploy mínimo.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SEVERITY_BY_ERROR = {
    "layout_changed": "P2",
    "data_validation": "P2",
    "timeout": "P2",
    "http_5xx": "P2",
    "connection_error": "P2",
    "rate_limited": "P2",
    "unexpected": "P2",
    "http_4xx": "P3",
    "unknown_source": "P3",
    "invalid_message": "P3",
}


def build_report(alert: dict) -> dict:
    error_type = alert.get("error_type", "unknown")
    source = alert.get("source", "desconhecida")
    return {
        "source": source,
        "rule": f"dead_letter_{error_type}",
        "severity": SEVERITY_BY_ERROR.get(error_type, "P2"),
        "title": f"Jobs de '{source}' enviados à DLQ por {error_type}",
        "details": {
            "last_job_id": alert.get("job_id"),
            "batch_id": alert.get("batch_id"),
            "target": f"{alert.get('category')}?page={alert.get('page')}",
            "attempts": alert.get("attempts"),
            "last_error": alert.get("message"),
            "action": "Corrigir a causa e executar redrive da DLQ.",
        },
    }


def post_report(report: dict, monitor_url: str, timeout: float = 10) -> dict:
    request = urllib.request.Request(
        f"{monitor_url.rstrip('/')}/api/incidents/report",
        data=json.dumps(report).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def lambda_handler(event: dict, context: object) -> dict:
    monitor_url = os.environ.get("MONITOR_URL", "http://monitor:8090")
    processed = 0
    for record in event.get("Records", []):
        alert = json.loads(record["Sns"]["Message"])
        result = post_report(build_report(alert), monitor_url)
        logger.info("incidente reportado: %s #%s", result.get("action"),
                    result.get("incident", {}).get("id"))
        processed += 1
    return {"processed": processed}
