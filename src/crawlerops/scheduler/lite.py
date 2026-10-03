"""Agendador leve: publica um lote de jobs no SQS a cada ``CAPTURE_INTERVAL_SECONDS``.

Equivalente a uma regra do EventBridge Scheduler disparando a cada N minutos. Use o
perfil ``airflow`` do docker compose para a versão orquestrada.
"""

from __future__ import annotations

import logging
import signal
import threading

from crawlerops.common.aws import aws_client
from crawlerops.common.config import Settings
from crawlerops.common.logging import configure_logging
from crawlerops.crawler.queue import SqsJobQueue
from crawlerops.scheduler.batch import build_batch, new_batch_id

logger = logging.getLogger("crawlerops.scheduler")


def main() -> None:
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    queue = SqsJobQueue(aws_client("sqs", settings), settings.sqs_queue_url, settings.sqs_dlq_url)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    logger.info("agendador iniciado", extra={"interval_s": settings.capture_interval_seconds})
    while not stop.is_set():
        batch_id = new_batch_id("lite")
        try:
            sent = queue.send(build_batch(batch_id))
            logger.info("lote enfileirado", extra={"batch_id": batch_id, "jobs": sent})
        except Exception:
            logger.exception("falha ao enfileirar lote", extra={"batch_id": batch_id})
        stop.wait(settings.capture_interval_seconds)


if __name__ == "__main__":
    main()
