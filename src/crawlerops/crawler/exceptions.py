"""Hierarquia de erros de captura.

A classificação decide o tratamento operacional:

- ``TransientError``: falha temporária (timeout, 5xx, 429). A mensagem volta para a fila
  com backoff e é tentada de novo até ``MAX_RECEIVE_COUNT``.
- ``PermanentError``: tentar de novo não resolve (layout mudou, dado inválido, 404).
  Vai direto para a DLQ e gera alerta, pois exige ação humana.
"""

from __future__ import annotations


class CaptureError(Exception):
    error_type = "unknown"
    retryable = True
    retry_in_process = False

    def __init__(self, message: str, *, http_status: int | None = None) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.raw_key: str | None = None


class TransientError(CaptureError):
    retryable = True


class FetchTimeoutError(TransientError):
    error_type = "timeout"


class ConnectionFailedError(TransientError):
    error_type = "connection_error"
    retry_in_process = True


class UpstreamServerError(TransientError):
    error_type = "http_5xx"
    retry_in_process = True


class RateLimitedError(TransientError):
    error_type = "rate_limited"

    def __init__(self, message: str, *, retry_after: int, http_status: int = 429) -> None:
        super().__init__(message, http_status=http_status)
        self.retry_after = retry_after


class UnexpectedError(TransientError):
    """Bug não previsto: tenta de novo, mas registra stacktrace para investigação."""

    error_type = "unexpected"


class PermanentError(CaptureError):
    retryable = False


class ClientHttpError(PermanentError):
    error_type = "http_4xx"


class LayoutChangedError(PermanentError):
    error_type = "layout_changed"


class DataValidationError(PermanentError):
    error_type = "data_validation"


class UnknownSourceError(PermanentError):
    error_type = "unknown_source"
