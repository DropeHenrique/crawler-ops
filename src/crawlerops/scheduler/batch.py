"""Montagem de lotes de captura. Usado pelo agendador leve e pela DAG do Airflow
(por isso depende apenas de ``boto3`` e da stdlib)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from crawlerops.common.models import CATEGORIES, PAGES_PER_CATEGORY, SOURCES, CaptureJob


def new_batch_id(prefix: str = "batch") -> str:
    return f"{prefix}-{datetime.now(UTC):%Y%m%dT%H%M%S}"


def build_batch(
    batch_id: str,
    sources: Iterable[str] = SOURCES,
    categories: Iterable[str] = CATEGORIES,
    pages: int = PAGES_PER_CATEGORY,
) -> list[CaptureJob]:
    categories = tuple(categories)
    return [
        CaptureJob(source=source, category=category, page=page, batch_id=batch_id)
        for source in sources
        for category in categories
        for page in range(1, pages + 1)
    ]
