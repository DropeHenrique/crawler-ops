from __future__ import annotations

from dataclasses import dataclass, field

from crawlerops.crawler.exceptions import DataValidationError
from crawlerops.crawler.models import Product


@dataclass(frozen=True)
class ValidationReport:
    valid: list[Product]
    invalid: list[tuple[Product, list[str]]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.valid) + len(self.invalid)

    @property
    def invalid_ratio(self) -> float:
        return len(self.invalid) / self.total if self.total else 0.0


def product_issues(product: Product) -> list[str]:
    issues = []
    if not product.sku:
        issues.append("sku vazio")
    if not product.name:
        issues.append("nome vazio")
    if product.price is None:
        issues.append("preço ausente")
    elif product.price <= 0:
        issues.append("preço não positivo")
    return issues


def validate_products(products: list[Product], max_invalid_ratio: float) -> ValidationReport:
    """Separa itens válidos e inválidos; se a proporção de inválidos passar do limite,
    a página inteira é rejeitada (provável quebra parcial de layout)."""
    valid, invalid = [], []
    for product in products:
        issues = product_issues(product)
        if issues:
            invalid.append((product, issues))
        else:
            valid.append(product)

    report = ValidationReport(valid=valid, invalid=invalid)
    if report.invalid_ratio > max_invalid_ratio:
        raise DataValidationError(
            f"{len(invalid)}/{report.total} itens inválidos "
            f"({report.invalid_ratio:.0%} > limite {max_invalid_ratio:.0%})"
        )
    return report
