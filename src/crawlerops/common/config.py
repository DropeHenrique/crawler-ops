from __future__ import annotations

import os
import socket
from dataclasses import dataclass


def _env(name: str, default: str) -> str:
    return os.environ.get(name) or default


@dataclass(frozen=True)
class Settings:
    aws_endpoint_url: str | None
    aws_region: str
    s3_bucket: str
    sqs_queue_url: str
    sqs_dlq_url: str
    sns_alerts_topic_arn: str | None
    database_url: str
    target_base_url: str
    http_timeout_seconds: float
    http_max_retries: int
    max_receive_count: int
    max_invalid_ratio: float
    worker_id: str
    metrics_port: int
    log_level: str
    capture_interval_seconds: int
    evaluation_interval_seconds: int
    monitor_window_minutes: int
    alert_webhook_url: str | None

    @classmethod
    def from_env(cls) -> Settings:
        local_sqs = "http://localhost:4566/000000000000"
        return cls(
            aws_endpoint_url=os.environ.get("AWS_ENDPOINT_URL") or None,
            aws_region=_env("AWS_DEFAULT_REGION", "us-east-1"),
            s3_bucket=_env("S3_BUCKET", "capture-data"),
            sqs_queue_url=_env("SQS_QUEUE_URL", f"{local_sqs}/capture-jobs"),
            sqs_dlq_url=_env("SQS_DLQ_URL", f"{local_sqs}/capture-jobs-dlq"),
            sns_alerts_topic_arn=os.environ.get("SNS_ALERTS_TOPIC_ARN") or None,
            database_url=_env(
                "DATABASE_URL", "postgresql://crawlerops:crawlerops@localhost:5433/crawlerops"
            ),
            target_base_url=_env("TARGET_BASE_URL", "http://localhost:8081"),
            http_timeout_seconds=float(_env("HTTP_TIMEOUT_SECONDS", "8")),
            http_max_retries=int(_env("HTTP_MAX_RETRIES", "2")),
            max_receive_count=int(_env("MAX_RECEIVE_COUNT", "3")),
            max_invalid_ratio=float(_env("MAX_INVALID_RATIO", "0.2")),
            worker_id=_env("WORKER_ID", socket.gethostname()),
            metrics_port=int(_env("METRICS_PORT", "9100")),
            log_level=_env("LOG_LEVEL", "INFO"),
            capture_interval_seconds=int(_env("CAPTURE_INTERVAL_SECONDS", "60")),
            evaluation_interval_seconds=int(_env("EVALUATION_INTERVAL_SECONDS", "20")),
            monitor_window_minutes=int(_env("MONITOR_WINDOW_MINUTES", "5")),
            alert_webhook_url=os.environ.get("ALERT_WEBHOOK_URL") or None,
        )
