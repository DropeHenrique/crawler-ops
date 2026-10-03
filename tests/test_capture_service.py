import pytest
from target_site.app import generate_products, render_alpha

from crawlerops.common.models import CaptureJob
from crawlerops.crawler.exceptions import DataValidationError, LayoutChangedError
from crawlerops.crawler.http_client import FetchResponse
from crawlerops.crawler.models import Product
from crawlerops.crawler.service import CaptureService


class FakeFetcher:
    def __init__(self, html: str) -> None:
        self.html = html

    def fetch(self, path: str) -> FetchResponse:
        return FetchResponse(url=f"http://site{path}", status_code=200, text=self.html, elapsed_ms=5)


class MemoryStorage:
    def __init__(self) -> None:
        self.raw: dict[str, str] = {}
        self.curated: dict[str, list[Product]] = {}

    def put_raw(self, job: CaptureJob, html: str) -> str:
        key = f"raw/{job.job_id}.html"
        self.raw[key] = html
        return key

    def put_products(self, job: CaptureJob, products: list[Product]) -> str:
        key = f"curated/{job.job_id}.json"
        self.curated[key] = products
        return key


def _html(**kwargs) -> str:
    opts = {"layout_v2": False, "drop_price": False, **kwargs}
    return render_alpha("eletronicos", generate_products("alpha", "eletronicos", 1), **opts)


def test_capture_stores_raw_and_curated(job_alpha):
    storage = MemoryStorage()

    outcome = CaptureService(FakeFetcher(_html()), storage).capture(job_alpha)

    assert len(outcome.products) == 20
    assert outcome.invalid_count == 0
    assert outcome.raw_key in storage.raw
    assert storage.curated[outcome.data_key] == outcome.products


def test_partial_page_keeps_valid_items_and_counts_invalid(job_alpha):
    outcome = CaptureService(FakeFetcher(_html(drop_price=True)), MemoryStorage()).capture(job_alpha)

    assert len(outcome.products) == 17
    assert outcome.invalid_count == 3


def test_too_many_invalid_items_rejects_page(job_alpha):
    service = CaptureService(FakeFetcher(_html(drop_price=True)), MemoryStorage(), max_invalid_ratio=0.1)

    with pytest.raises(DataValidationError):
        service.capture(job_alpha)


def test_layout_change_keeps_raw_html_for_diagnosis(job_alpha):
    storage = MemoryStorage()

    with pytest.raises(LayoutChangedError) as exc_info:
        CaptureService(FakeFetcher(_html(layout_v2=True)), storage).capture(job_alpha)

    assert exc_info.value.raw_key in storage.raw
    assert exc_info.value.http_status == 200
    assert storage.curated == {}
