from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from crawlerops.common.models import CaptureJob


@dataclass(frozen=True)
class Product:
    sku: str
    name: str
    price: Decimal | None
    available: bool
    url: str
    source: str
    category: str
    currency: str = "BRL"

    def to_dict(self) -> dict:
        return {
            "sku": self.sku,
            "name": self.name,
            "price": str(self.price) if self.price is not None else None,
            "currency": self.currency,
            "available": self.available,
            "url": self.url,
            "source": self.source,
            "category": self.category,
        }


@dataclass(frozen=True)
class CaptureOutcome:
    products: list[Product]
    invalid_count: int
    raw_key: str
    data_key: str
    http_status: int


@dataclass(frozen=True)
class CaptureRun:
    """Registro de uma tentativa de captura (persistido no RDS para monitoramento)."""

    job: CaptureJob
    target_url: str
    status: str
    terminal: bool
    attempt: int
    duration_ms: int
    worker_id: str
    started_at: datetime
    items_count: int = 0
    invalid_items: int = 0
    error_type: str | None = None
    error_message: str | None = None
    http_status: int | None = None
    s3_raw_key: str | None = None
    s3_data_key: str | None = None
