from __future__ import annotations

import re
from abc import ABC, abstractmethod
from decimal import Decimal, InvalidOperation
from typing import ClassVar
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from crawlerops.common.models import CaptureJob
from crawlerops.crawler.exceptions import LayoutChangedError
from crawlerops.crawler.models import Product


class ProductParser(ABC):
    """Template Method: o fluxo de parsing é fixo, cada fonte implementa só o que muda.

    Se o contêiner principal ou os itens não forem encontrados, assume-se que o site mudou
    de layout (``LayoutChangedError``), um erro permanente que precisa de correção no código.
    """

    source: ClassVar[str]
    container_selector: ClassVar[str]
    item_selector: ClassVar[str]

    def parse(self, html: str, job: CaptureJob, page_url: str) -> list[Product]:
        soup = BeautifulSoup(html, "html.parser")
        container = soup.select_one(self.container_selector)
        if container is None:
            raise LayoutChangedError(
                f"[{self.source}] contêiner '{self.container_selector}' não encontrado"
            )
        nodes = container.select(self.item_selector)
        if not nodes:
            raise LayoutChangedError(
                f"[{self.source}] nenhum item '{self.item_selector}' no contêiner"
            )
        return [self.parse_item(node, job, page_url) for node in nodes]

    @abstractmethod
    def parse_item(self, node: Tag, job: CaptureJob, page_url: str) -> Product: ...

    @staticmethod
    def text(node: Tag, selector: str) -> str:
        found = node.select_one(selector)
        return found.get_text(strip=True) if found else ""

    @staticmethod
    def absolute_url(node: Tag, selector: str, page_url: str) -> str:
        link = node.select_one(selector)
        href = link.get("href") if link else None
        return urljoin(page_url, str(href)) if href else page_url

    @staticmethod
    def parse_decimal(raw: str, *, decimal_comma: bool) -> Decimal | None:
        cleaned = re.sub(r"[^\d,.\-]", "", raw)
        if not cleaned:
            return None
        if decimal_comma:
            cleaned = cleaned.replace(".", "").replace(",", ".")
        try:
            return Decimal(cleaned)
        except InvalidOperation:
            return None
