from __future__ import annotations

from bs4 import Tag

from crawlerops.common.models import CaptureJob
from crawlerops.crawler.models import Product
from crawlerops.crawler.parsers.base import ProductParser


class BetaParser(ProductParser):
    """Loja Beta: catálogo em tabela, preço com ponto decimal (``1234.56``)."""

    source = "beta"
    container_selector = "table#products"
    item_selector = "tbody tr[data-sku]"

    def parse_item(self, node: Tag, job: CaptureJob, page_url: str) -> Product:
        return Product(
            sku=str(node.get("data-sku", "")).strip(),
            name=self.text(node, "td.name"),
            price=self.parse_decimal(self.text(node, "td.price"), decimal_comma=False),
            available=self.text(node, "td.availability") == "available",
            url=self.absolute_url(node, "td.name a", page_url),
            source=job.source,
            category=job.category,
        )
