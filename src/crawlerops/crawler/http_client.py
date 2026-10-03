from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from crawlerops.crawler.exceptions import (
    ClientHttpError,
    ConnectionFailedError,
    FetchTimeoutError,
    RateLimitedError,
    TransientError,
    UpstreamServerError,
)

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {"User-Agent": "crawlerops-bot/0.1 (+sustentacao)"}


@dataclass(frozen=True)
class FetchResponse:
    url: str
    status_code: int
    text: str
    elapsed_ms: int


class HttpFetcher:
    """Cliente HTTP que traduz falhas de rede/HTTP para a hierarquia de ``CaptureError``.

    Erros "baratos" (5xx, conexão recusada) são re-tentados aqui com backoff exponencial
    e jitter. Timeouts e 429 sobem direto: o retry deles é feito via SQS, sem prender
    o worker.
    """

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float,
        max_retries: int = 2,
        backoff_base: float = 0.5,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client or httpx.Client(
            base_url=base_url,
            timeout=timeout_seconds,
            headers=DEFAULT_HEADERS,
            follow_redirects=True,
        )
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._sleep = sleep

    def fetch(self, path: str) -> FetchResponse:
        attempt = 0
        while True:
            try:
                return self._fetch_once(path)
            except TransientError as exc:
                if not exc.retry_in_process or attempt >= self._max_retries:
                    raise
                delay = self._backoff_base * (2**attempt) + random.uniform(0, self._backoff_base)
                attempt += 1
                logger.warning(
                    "retry http",
                    extra={"path": path, "attempt": attempt, "delay_s": round(delay, 2),
                           "error_type": exc.error_type},
                )
                self._sleep(delay)

    def _fetch_once(self, path: str) -> FetchResponse:
        started = time.perf_counter()
        try:
            response = self._client.get(path)
        except httpx.TimeoutException as exc:
            raise FetchTimeoutError(f"timeout ao acessar {path}") from exc
        except httpx.TransportError as exc:
            raise ConnectionFailedError(f"falha de conexão em {path}: {exc}") from exc

        status = response.status_code
        if status == 429:
            retry_after = _parse_retry_after(response.headers.get("Retry-After"))
            raise RateLimitedError(f"rate limit em {path}", retry_after=retry_after)
        if status >= 500:
            raise UpstreamServerError(f"HTTP {status} em {path}", http_status=status)
        if status >= 400:
            raise ClientHttpError(f"HTTP {status} em {path}", http_status=status)

        return FetchResponse(
            url=str(response.url),
            status_code=status,
            text=response.text,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )

    def close(self) -> None:
        self._client.close()


def _parse_retry_after(value: str | None, default: int = 30) -> int:
    try:
        return max(1, int(value)) if value else default
    except ValueError:
        return default
