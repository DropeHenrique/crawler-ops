from __future__ import annotations

from bs4 import Tag

from crawlerops.common.models import CaptureJob
from crawlerops.crawler.models import Product
from crawlerops.crawler.parsers.base import ProductParser


class AlphaParser(ProductParser):
    """Loja Alpha: catálogo em cards, preço em formato brasileiro (``R$ 1.234,56``)."""

    source = "alpha"
    container_selector = "main#catalog"
    item_selector = "div.product-card"

    def parse_item(self, node: Tag, job: CaptureJob, page_url: str) -> Product:
        return Product(
            sku=str(node.get("data-sku", "")).strip(),
            name=self.text(node, ".product-title"),
            price=self.parse_decimal(self.text(node, ".price"), decimal_comma=True),
            available=node.select_one(".stock.in-stock") is not None,
            url=self.absolute_url(node, ".product-title a", page_url),
            source=job.source,
            category=job.category,
        )
