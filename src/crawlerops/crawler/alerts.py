from __future__ import annotations

import json
import logging
from typing import Any, Protocol

from crawlerops.common.models import CaptureJob

logger = logging.getLogger(__name__)


class AlertPublisher(Protocol):
    def publish_failure(
        self, job: CaptureJob, *, error_type: str, message: str, attempts: int
    ) -> None: ...


class SnsAlertPublisher:
    """Publica falhas definitivas no SNS; a Lambda ``failure-alert`` abre o incidente."""

    def __init__(self, sns_client: Any, topic_arn: str | None) -> None:
        self._sns = sns_client
        self._topic_arn = topic_arn

    def publish_failure(
        self, job: CaptureJob, *, error_type: str, message: str, attempts: int
    ) -> None:
        if not self._topic_arn:
            return
        payload = {
            "event": "capture_failed",
            "source": job.source,
            "category": job.category,
            "page": job.page,
            "job_id": job.job_id,
            "batch_id": job.batch_id,
            "error_type": error_type,
            "message": message,
            "attempts": attempts,
        }
        try:
            self._sns.publish(
                TopicArn=self._topic_arn,
                Subject=f"Falha de captura [{job.source}] {error_type}"[:100],
                Message=json.dumps(payload, ensure_ascii=False),
            )
        except Exception:
            logger.exception("falha ao publicar alerta no SNS", extra={"job_id": job.job_id})
