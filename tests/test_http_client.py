import httpx
import pytest
import respx

from crawlerops.crawler.exceptions import (
    ClientHttpError,
    ConnectionFailedError,
    FetchTimeoutError,
    RateLimitedError,
    UpstreamServerError,
)
from crawlerops.crawler.http_client import HttpFetcher

BASE = "http://target"


@pytest.fixture
def sleeps() -> list[float]:
    return []


@pytest.fixture
def fetcher(sleeps) -> HttpFetcher:
    return HttpFetcher(BASE, timeout_seconds=1, max_retries=2, sleep=sleeps.append)


@respx.mock
def test_success_returns_body(fetcher):
    respx.get(f"{BASE}/alpha/casa").respond(200, text="<html>ok</html>")

    response = fetcher.fetch("/alpha/casa")

    assert response.status_code == 200
    assert response.text == "<html>ok</html>"


@respx.mock
def test_5xx_is_retried_in_process_then_succeeds(fetcher, sleeps):
    route = respx.get(f"{BASE}/p").mock(
        side_effect=[httpx.Response(500), httpx.Response(502), httpx.Response(200, text="ok")]
    )

    assert fetcher.fetch("/p").text == "ok"
    assert route.call_count == 3
    assert len(sleeps) == 2
    assert sleeps[1] > sleeps[0]


@respx.mock
def test_5xx_exhausts_retries(fetcher):
    respx.get(f"{BASE}/p").respond(503)

    with pytest.raises(UpstreamServerError) as exc_info:
        fetcher.fetch("/p")

    assert exc_info.value.http_status == 503
    assert exc_info.value.retryable is True


@respx.mock
def test_timeout_is_not_retried_in_process(fetcher, sleeps):
    route = respx.get(f"{BASE}/p").mock(side_effect=httpx.ReadTimeout("lento"))

    with pytest.raises(FetchTimeoutError):
        fetcher.fetch("/p")

    assert route.call_count == 1
    assert sleeps == []


@respx.mock
def test_429_exposes_retry_after(fetcher):
    respx.get(f"{BASE}/p").respond(429, headers={"Retry-After": "42"})

    with pytest.raises(RateLimitedError) as exc_info:
        fetcher.fetch("/p")

    assert exc_info.value.retry_after == 42


@respx.mock
def test_404_is_permanent(fetcher):
    respx.get(f"{BASE}/p").respond(404)

    with pytest.raises(ClientHttpError) as exc_info:
        fetcher.fetch("/p")

    assert exc_info.value.retryable is False


@respx.mock
def test_connection_error_is_classified(fetcher):
    respx.get(f"{BASE}/p").mock(side_effect=httpx.ConnectError("recusado"))

    with pytest.raises(ConnectionFailedError):
        fetcher.fetch("/p")
