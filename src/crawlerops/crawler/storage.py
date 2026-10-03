from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Protocol

from crawlerops.common.models import CaptureJob
from crawlerops.crawler.models import Product


class CaptureStorage(Protocol):
    def put_raw(self, job: CaptureJob, html: str) -> str: ...

    def put_products(self, job: CaptureJob, products: list[Product]) -> str: ...


class S3CaptureStorage:
    """Data lake em camadas: ``raw/`` guarda o HTML original (essencial para diagnosticar
    quebras de layout) e ``curated/`` guarda os produtos validados, particionados por data."""

    def __init__(self, s3_client: Any, bucket: str) -> None:
        self._s3 = s3_client
        self._bucket = bucket

    def put_raw(self, job: CaptureJob, html: str) -> str:
        key = f"raw/{job.source}/dt={_today()}/{job.job_id}.html"
        self._s3.put_object(
            Bucket=self._bucket, Key=key, Body=html.encode(), ContentType="text/html; charset=utf-8"
        )
        return key

    def put_products(self, job: CaptureJob, products: list[Product]) -> str:
        key = f"curated/{job.source}/{job.category}/dt={_today()}/{job.job_id}.json"
        payload = {
            "job_id": job.job_id,
            "batch_id": job.batch_id,
            "source": job.source,
            "category": job.category,
            "page": job.page,
            "captured_at": datetime.now(UTC).isoformat(),
            "items": [p.to_dict() for p in products],
        }
        self._s3.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=json.dumps(payload, ensure_ascii=False).encode(),
            ContentType="application/json",
        )
        return key


def _today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")
