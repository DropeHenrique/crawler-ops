from decimal import Decimal

import pytest
from target_site.app import generate_products, render_alpha, render_beta

from crawlerops.crawler.exceptions import LayoutChangedError, UnknownSourceError
from crawlerops.crawler.parsers import AlphaParser, BetaParser, get_parser
from crawlerops.crawler.parsers.base import ProductParser


def _alpha_html(**kwargs) -> str:
    defaults = {"layout_v2": False, "drop_price": False}
    return render_alpha("eletronicos", generate_products("alpha", "eletronicos", 1), **{**defaults, **kwargs})


def _beta_html(**kwargs) -> str:
    defaults = {"layout_v2": False, "drop_price": False}
    return render_beta("livros", generate_products("beta", "livros", 2), **{**defaults, **kwargs})


def test_alpha_parser_extracts_all_products(job_alpha):
    expected = generate_products("alpha", "eletronicos", 1)

    products = AlphaParser().parse(_alpha_html(), job_alpha, "http://site/alpha/eletronicos?page=1")

    assert len(products) == len(expected)
    first = products[0]
    assert first.sku == expected[0].sku
    assert first.name == expected[0].name
    assert first.price == Decimal(f"{expected[0].price:.2f}")
    assert first.available is expected[0].available
    assert first.url == f"http://site/alpha/produto/{expected[0].sku}"
    assert first.source == "alpha" and first.category == "eletronicos"


def test_beta_parser_extracts_all_products(job_beta):
    expected = generate_products("beta", "livros", 2)

    products = BetaParser().parse(_beta_html(), job_beta, "http://site/beta/livros?page=2")

    assert [p.sku for p in products] == [p.sku for p in expected]
    assert products[3].price == Decimal(f"{expected[3].price:.2f}")
    assert products[3].available is expected[3].available


@pytest.mark.parametrize(
    ("parser", "html_factory", "job_fixture"),
    [(AlphaParser, _alpha_html, "job_alpha"), (BetaParser, _beta_html, "job_beta")],
)
def test_layout_change_raises_permanent_error(parser, html_factory, job_fixture, request):
    job = request.getfixturevalue(job_fixture)

    with pytest.raises(LayoutChangedError) as exc_info:
        parser().parse(html_factory(layout_v2=True), job, "http://site/")

    assert exc_info.value.retryable is False


def test_container_without_items_is_layout_change(job_alpha):
    html = "<main id='catalog'><p>sem produtos</p></main>"

    with pytest.raises(LayoutChangedError, match="nenhum item"):
        AlphaParser().parse(html, job_alpha, "http://site/")


def test_missing_price_is_parsed_as_none(job_alpha):
    products = AlphaParser().parse(_alpha_html(drop_price=True), job_alpha, "http://site/")

    assert sum(p.price is None for p in products) == 3


@pytest.mark.parametrize(
    ("raw", "decimal_comma", "expected"),
    [
        ("R$ 1.234,56", True, Decimal("1234.56")),
        ("R$ 19,90", True, Decimal("19.90")),
        ("1234.56", False, Decimal("1234.56")),
        ("", False, None),
        ("indisponível", True, None),
    ],
)
def test_parse_decimal(raw, decimal_comma, expected):
    assert ProductParser.parse_decimal(raw, decimal_comma=decimal_comma) == expected


def test_registry_returns_parser_by_source():
    assert isinstance(get_parser("alpha"), AlphaParser)
    assert isinstance(get_parser("beta"), BetaParser)
    with pytest.raises(UnknownSourceError):
        get_parser("gamma")
