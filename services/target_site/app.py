"""Site-alvo falso com injeção de falhas controlável.

Simula duas lojas com layouts diferentes que são capturadas pelos crawlers:

- ``alpha``: catálogo em cards (``div.product-card``), preço no formato ``R$ 1.234,56``.
- ``beta``: catálogo em tabela (``table#products``), preço no formato ``1234.56``.

O endpoint ``/admin/chaos`` permite injetar falhas por loja para treinar a sustentação.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field

SOURCES = ("alpha", "beta")
CATEGORIES = ("eletronicos", "livros", "casa")
PAGES_PER_CATEGORY = 2
ITEMS_PER_PAGE = 20

_ADJECTIVES = ("Pro", "Max", "Lite", "Plus", "Ultra", "Smart", "Eco", "Prime", "Mini", "Neo")
_NOUNS = {
    "eletronicos": ("Fone", "Notebook", "Monitor", "Teclado", "Mouse", "Smartphone", "Tablet"),
    "livros": ("Romance", "Guia", "Manual", "Antologia", "Biografia", "Coletânea", "Atlas"),
    "casa": ("Luminária", "Cadeira", "Panela", "Tapete", "Almofada", "Prateleira", "Cafeteira"),
}


class ChaosMode(StrEnum):
    NONE = "none"
    SLOW = "slow"
    TIMEOUT = "timeout"
    ERROR_500 = "error_500"
    UNAVAILABLE = "unavailable"
    RATE_LIMIT = "rate_limit"
    LAYOUT_CHANGE = "layout_change"
    PARTIAL = "partial"


CHAOS_DESCRIPTIONS = {
    ChaosMode.NONE: "Operação normal",
    ChaosMode.SLOW: "Respostas lentas (4-6s): degradação de latência",
    ChaosMode.TIMEOUT: "Resposta após 30s: estoura o timeout do crawler",
    ChaosMode.ERROR_500: "HTTP 500: erro interno no site",
    ChaosMode.UNAVAILABLE: "HTTP 503: site fora do ar",
    ChaosMode.RATE_LIMIT: "HTTP 429 com Retry-After: bloqueio por excesso de requisições",
    ChaosMode.LAYOUT_CHANGE: "HTML com estrutura nova: quebra o parser",
    ChaosMode.PARTIAL: "Alguns produtos sem preço: problema de qualidade de dados",
}


@dataclass
class ChaosState:
    mode: ChaosMode = ChaosMode.NONE
    probability: float = 1.0

    def should_fail(self, rng: random.Random) -> bool:
        return self.mode is not ChaosMode.NONE and rng.random() < self.probability


@dataclass(frozen=True)
class Product:
    sku: str
    name: str
    price: float
    available: bool


class ChaosRequest(BaseModel):
    source: Literal["alpha", "beta", "all"] = "all"
    mode: ChaosMode
    probability: float = Field(default=1.0, ge=0.0, le=1.0)


app = FastAPI(title="Target Site (lojas simuladas)")
_chaos: dict[str, ChaosState] = {source: ChaosState() for source in SOURCES}
_rng = random.Random()


def generate_products(source: str, category: str, page: int) -> list[Product]:
    rng = random.Random(f"{source}-{category}-{page}")
    products = []
    for index in range(ITEMS_PER_PAGE):
        number = (page - 1) * ITEMS_PER_PAGE + index + 1
        name = f"{rng.choice(_NOUNS[category])} {rng.choice(_ADJECTIVES)} {number}"
        products.append(
            Product(
                sku=f"{source.upper()}-{category[:3].upper()}-{number:04d}",
                name=name,
                price=round(rng.uniform(19.9, 4999.9), 2),
                available=rng.random() > 0.15,
            )
        )
    return products


def format_brl(value: float) -> str:
    integer, cents = f"{value:,.2f}".split(".")
    return f"R$ {integer.replace(',', '.')},{cents}"


def _page(title: str, body: str) -> str:
    return (
        "<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'>"
        f"<title>{title}</title></head><body>{body}</body></html>"
    )


def render_alpha(category: str, products: list[Product], *, layout_v2: bool, drop_price: bool) -> str:
    items = []
    for i, p in enumerate(products):
        price = "" if drop_price and i % 7 == 0 else format_brl(p.price)
        stock = "Em estoque" if p.available else "Esgotado"
        if layout_v2:
            items.append(
                f"<article class='item-tile' data-id='{p.sku}'>"
                f"<h3 class='tile-name'><a href='/alpha/produto/{p.sku}'>{p.name}</a></h3>"
                f"<div class='tile-price'>{price}</div><small class='tile-stock'>{stock}</small></article>"
            )
        else:
            stock_cls = "in-stock" if p.available else "out-of-stock"
            items.append(
                f"<div class='product-card' data-sku='{p.sku}'>"
                f"<h2 class='product-title'><a href='/alpha/produto/{p.sku}'>{p.name}</a></h2>"
                f"<span class='price'>{price}</span><span class='stock {stock_cls}'>{stock}</span></div>"
            )
    container = "section id='vitrine'" if layout_v2 else f"main id='catalog' data-category='{category}'"
    tag = container.split()[0]
    return _page(f"Loja Alpha - {category}", f"<{container}>{''.join(items)}</{tag}>")


def render_beta(category: str, products: list[Product], *, layout_v2: bool, drop_price: bool) -> str:
    rows = []
    for i, p in enumerate(products):
        price = "" if drop_price and i % 7 == 0 else f"{p.price:.2f}"
        availability = "available" if p.available else "out_of_stock"
        if layout_v2:
            rows.append(
                f"<li class='entry' data-code='{p.sku}'><b>{p.name}</b> - <em>{price}</em></li>"
            )
        else:
            rows.append(
                f"<tr data-sku='{p.sku}'><td class='name'><a href='/beta/p/{p.sku}'>{p.name}</a></td>"
                f"<td class='price'>{price}</td><td class='availability'>{availability}</td></tr>"
            )
    if layout_v2:
        body = f"<ul class='catalog-list'>{''.join(rows)}</ul>"
    else:
        body = (
            f"<table id='products' data-category='{category}'><thead><tr><th>Produto</th>"
            f"<th>Preço</th><th>Disponibilidade</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"
        )
    return _page(f"Loja Beta - {category}", body)


RENDERERS = {"alpha": render_alpha, "beta": render_beta}


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/admin/chaos")
def get_chaos() -> dict:
    return {
        "sources": {s: {**asdict(st), "mode": st.mode.value} for s, st in _chaos.items()},
        "modes": {m.value: d for m, d in CHAOS_DESCRIPTIONS.items()},
    }


@app.post("/admin/chaos")
def set_chaos(request: ChaosRequest) -> dict:
    targets = SOURCES if request.source == "all" else (request.source,)
    for source in targets:
        _chaos[source] = ChaosState(mode=request.mode, probability=request.probability)
    return get_chaos()


@app.post("/admin/chaos/reset")
def reset_chaos() -> dict:
    for source in SOURCES:
        _chaos[source] = ChaosState()
    return get_chaos()


@app.get("/{source}/{category}")
async def catalog(source: str, category: str, page: int = 1) -> Response:
    if source not in SOURCES or category not in CATEGORIES:
        raise HTTPException(status_code=404, detail="Página não encontrada")
    if not 1 <= page <= PAGES_PER_CATEGORY:
        raise HTTPException(status_code=404, detail="Página inexistente")

    state = _chaos[source]
    failing = state.should_fail(_rng)
    mode = state.mode if failing else ChaosMode.NONE

    match mode:
        case ChaosMode.SLOW:
            await asyncio.sleep(_rng.uniform(4, 6))
        case ChaosMode.TIMEOUT:
            await asyncio.sleep(30)
        case ChaosMode.ERROR_500:
            return JSONResponse({"error": "internal server error"}, status_code=500)
        case ChaosMode.UNAVAILABLE:
            return HTMLResponse("<h1>Service Unavailable</h1>", status_code=503)
        case ChaosMode.RATE_LIMIT:
            return HTMLResponse(
                "<h1>Too Many Requests</h1>", status_code=429, headers={"Retry-After": "20"}
            )

    html = RENDERERS[source](
        category,
        generate_products(source, category, page),
        layout_v2=mode is ChaosMode.LAYOUT_CHANGE,
        drop_price=mode is ChaosMode.PARTIAL,
    )
    return HTMLResponse(html)
