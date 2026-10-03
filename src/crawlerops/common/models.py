from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field

SOURCES = ("alpha", "beta")
CATEGORIES = ("eletronicos", "livros", "casa")
PAGES_PER_CATEGORY = 2


@dataclass(frozen=True)
class CaptureJob:
    """Unidade de trabalho publicada na fila SQS: capturar uma página de catálogo."""

    source: str
    category: str
    page: int
    batch_id: str
    job_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    @property
    def url_path(self) -> str:
        return f"/{self.source}/{self.category}?page={self.page}"

    def to_message(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_message(cls, body: str) -> CaptureJob:
        try:
            data = json.loads(body)
            job = cls(
                source=str(data["source"]),
                category=str(data["category"]),
                page=int(data["page"]),
                batch_id=str(data["batch_id"]),
                job_id=str(data["job_id"]),
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"mensagem inválida: {exc}") from exc
        if job.page < 1:
            raise ValueError("mensagem inválida: page deve ser >= 1")
        return job
