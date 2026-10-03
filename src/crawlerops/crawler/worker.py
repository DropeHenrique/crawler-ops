"""Worker de captura: consome jobs do SQS. Roda como task ECS/Fargate (aqui, réplicas Docker).

Política de falhas:

- sucesso → registra no RDS e remove a mensagem;
- erro permanente → DLQ imediata + alerta via SNS;
- erro transitório → backoff exponencial via visibility timeout; na última tentativa
  (``MAX_RECEIVE_COUNT``) vai para a DLQ + alerta.
"""

from __future__ import annotations

import logging
import signal
import time
from datetime import UTC, datetime

from prometheus_client import start_http_server

from crawlerops.common.aws import aws_client
from crawlerops.common.config import Settings
from crawlerops.common.db import Database
from crawlerops.common.logging import configure_logging
from crawlerops.common.models import CaptureJob
from crawlerops.crawler import metrics
from crawlerops.crawler.alerts import AlertPublisher, SnsAlertPublisher
from crawlerops.crawler.exceptions import CaptureError, RateLimitedError, UnexpectedError
from crawlerops.crawler.http_client import HttpFetcher
from crawlerops.crawler.models import CaptureOutcome, CaptureRun
from crawlerops.crawler.queue import ReceivedMessage, SqsJobQueue
from crawlerops.crawler.repository import PostgresRunRepository, RunRepository
from crawlerops.crawler.service import CaptureService
from crawlerops.crawler.storage import S3CaptureStorage

logger = logging.getLogger("crawlerops.worker")


class Worker:
    def __init__(
        self,
        queue: SqsJobQueue,
        service: CaptureService,
        repository: RunRepository,
        alerts: AlertPublisher,
        *,
        target_base_url: str,
        worker_id: str,
        max_receive_count: int = 3,
        retry_base_seconds: int = 10,
    ) -> None:
        self._queue = queue
        self._service = service
        self._repository = repository
        self._alerts = alerts
        self._target_base_url = target_base_url.rstrip("/")
        self._worker_id = worker_id
        self._max_receive_count = max_receive_count
        self._retry_base_seconds = retry_base_seconds
        self._running = True

    def stop(self, *_: object) -> None:
        logger.info("sinal de parada recebido: finalizando após o lote atual")
        self._running = False

    def run_forever(self) -> None:
        logger.info("worker iniciado", extra={"worker_id": self._worker_id})
        while self._running:
            try:
                messages = self._queue.receive()
            except Exception:
                logger.exception("falha ao ler a fila; nova tentativa em 5s")
                time.sleep(5)
                continue
            for message in messages:
                self.process(message)
        logger.info("worker finalizado")

    def process(self, message: ReceivedMessage) -> None:
        try:
            job = CaptureJob.from_message(message.body)
        except ValueError as exc:
            logger.error("mensagem malformada enviada à DLQ", extra={"message_id": message.message_id})
            self._queue.dead_letter(message, error_type="invalid_message", reason=str(exc))
            return

        started_at = datetime.now(UTC)
        t0 = time.perf_counter()
        metrics.IN_FLIGHT.inc()
        try:
            outcome = self._service.capture(job)
        except CaptureError as exc:
            self._on_failure(message, job, exc, started_at, t0)
        except Exception as exc:
            logger.exception("erro inesperado na captura", extra={"job_id": job.job_id})
            self._on_failure(message, job, UnexpectedError(repr(exc)), started_at, t0)
        else:
            self._on_success(message, job, outcome, started_at, t0)
        finally:
            metrics.IN_FLIGHT.dec()

    def _on_success(
        self, message: ReceivedMessage, job: CaptureJob, outcome: CaptureOutcome,
        started_at: datetime, t0: float,
    ) -> None:
        duration = time.perf_counter() - t0
        self._record(CaptureRun(
            job=job, target_url=self._url(job), status="success", terminal=True,
            attempt=message.receive_count, duration_ms=int(duration * 1000),
            worker_id=self._worker_id, started_at=started_at,
            items_count=len(outcome.products), invalid_items=outcome.invalid_count,
            http_status=outcome.http_status, s3_raw_key=outcome.raw_key, s3_data_key=outcome.data_key,
        ))
        self._queue.delete(message)

        metrics.CAPTURES.labels(job.source, "success", "").inc()
        metrics.ITEMS.labels(job.source).inc(len(outcome.products))
        metrics.INVALID_ITEMS.labels(job.source).inc(outcome.invalid_count)
        metrics.DURATION.labels(job.source).observe(duration)
        metrics.LAST_SUCCESS.labels(job.source).set_to_current_time()
        logger.info("captura concluída", extra={
            "job_id": job.job_id, "source": job.source, "category": job.category,
            "page": job.page, "items": len(outcome.products),
            "invalid": outcome.invalid_count, "duration_ms": int(duration * 1000),
        })

    def _on_failure(
        self, message: ReceivedMessage, job: CaptureJob, exc: CaptureError,
        started_at: datetime, t0: float,
    ) -> None:
        attempt = message.receive_count
        final = not exc.retryable or attempt >= self._max_receive_count
        duration = time.perf_counter() - t0
        self._record(CaptureRun(
            job=job, target_url=self._url(job), status="failed", terminal=final,
            attempt=attempt, duration_ms=int(duration * 1000), worker_id=self._worker_id,
            started_at=started_at, error_type=exc.error_type, error_message=str(exc)[:2000],
            http_status=exc.http_status, s3_raw_key=exc.raw_key,
        ))
        metrics.CAPTURES.labels(job.source, "failed", exc.error_type).inc()
        metrics.DURATION.labels(job.source).observe(duration)

        log_ctx = {
            "job_id": job.job_id, "source": job.source, "category": job.category,
            "page": job.page, "attempt": attempt, "error_type": exc.error_type, "error": str(exc),
        }
        if final:
            self._queue.dead_letter(message, error_type=exc.error_type, reason=str(exc))
            self._alerts.publish_failure(
                job, error_type=exc.error_type, message=str(exc), attempts=attempt
            )
            metrics.DEAD_LETTERED.labels(job.source, exc.error_type).inc()
            logger.error("falha definitiva: job enviado à DLQ", extra=log_ctx)
            return

        delay = (
            exc.retry_after if isinstance(exc, RateLimitedError)
            else self._retry_base_seconds * 2 ** (attempt - 1)
        )
        self._queue.retry_later(message, delay)
        logger.warning("falha transitória: nova tentativa agendada", extra={**log_ctx, "retry_in_s": delay})

    def _record(self, run: CaptureRun) -> None:
        try:
            self._repository.record(run)
        except Exception:
            logger.exception("falha ao registrar execução no banco", extra={"job_id": run.job.job_id})

    def _url(self, job: CaptureJob) -> str:
        return f"{self._target_base_url}{job.url_path}"


def build_worker(settings: Settings) -> Worker:
    queue = SqsJobQueue(aws_client("sqs", settings), settings.sqs_queue_url, settings.sqs_dlq_url)
    fetcher = HttpFetcher(
        settings.target_base_url,
        timeout_seconds=settings.http_timeout_seconds,
        max_retries=settings.http_max_retries,
    )
    service = CaptureService(
        fetcher,
        S3CaptureStorage(aws_client("s3", settings), settings.s3_bucket),
        max_invalid_ratio=settings.max_invalid_ratio,
    )
    return Worker(
        queue,
        service,
        PostgresRunRepository(Database(settings.database_url)),
        SnsAlertPublisher(aws_client("sns", settings), settings.sns_alerts_topic_arn),
        target_base_url=settings.target_base_url,
        worker_id=settings.worker_id,
        max_receive_count=settings.max_receive_count,
    )


def main() -> None:
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    start_http_server(settings.metrics_port)
    worker = build_worker(settings)
    signal.signal(signal.SIGTERM, worker.stop)
    signal.signal(signal.SIGINT, worker.stop)
    worker.run_forever()


if __name__ == "__main__":
    main()
