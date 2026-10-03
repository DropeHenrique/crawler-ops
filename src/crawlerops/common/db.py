from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row


class Database:
    """Abre uma conexão curta por operação: simples, thread-safe e resiliente a quedas do RDS."""

    def __init__(self, dsn: str, connect_timeout: int = 5) -> None:
        self._dsn = dsn
        self._connect_timeout = connect_timeout

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection]:
        with psycopg.connect(
            self._dsn, row_factory=dict_row, connect_timeout=self._connect_timeout
        ) as conn:
            yield conn

    def ping(self) -> bool:
        try:
            with self.connection() as conn:
                conn.execute("SELECT 1")
            return True
        except psycopg.Error:
            return False
