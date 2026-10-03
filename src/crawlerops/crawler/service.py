from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from crawlerops.common.models import CaptureJob
from crawlerops.crawler.exceptions import CaptureError
from crawlerops.crawler.http_client import FetchResponse
from crawlerops.crawler.models import CaptureOutcome
from crawlerops.crawler.parsers import ProductParser, get_parser
from crawlerops.crawler.storage import CaptureStorage
from crawlerops.crawler.validation import validate_products


class Fetcher(Protocol):
    def fetch(self, path: str) -> FetchResponse: ...


class CaptureService:
    """Orquestra uma captura: busca → guarda HTML bruto → parseia → valida → guarda curado."""

    def __init__(
        self,
        fetcher: Fetcher,
        storage: CaptureStorage,
        parser_factory: Callable[[str], ProductParser] = get_parser,
        max_invalid_ratio: float = 0.2,
    ) -> None:
        self._fetcher = fetcher
        self._storage = storage
        self._parser_factory = parser_factory
        self._max_invalid_ratio = max_invalid_ratio

    def capture(self, job: CaptureJob) -> CaptureOutcome:
        parser = self._parser_factory(job.source)
        response = self._fetcher.fetch(job.url_path)
        raw_key = self._storage.put_raw(job, response.text)
        try:
            products = parser.parse(response.text, job, response.url)
            report = validate_products(products, self._max_invalid_ratio)
        except CaptureError as exc:
            exc.raw_key = raw_key
            exc.http_status = exc.http_status or response.status_code
            raise

        data_key = self._storage.put_products(job, report.valid)
        return CaptureOutcome(
            products=report.valid,
            invalid_count=len(report.invalid),
            raw_key=raw_key,
            data_key=data_key,
            http_status=response.status_code,
        )
