from crawlerops.crawler.exceptions import UnknownSourceError
from crawlerops.crawler.parsers.alpha import AlphaParser
from crawlerops.crawler.parsers.base import ProductParser
from crawlerops.crawler.parsers.beta import BetaParser

_REGISTRY: dict[str, type[ProductParser]] = {
    parser.source: parser for parser in (AlphaParser, BetaParser)
}


def get_parser(source: str) -> ProductParser:
    try:
        return _REGISTRY[source]()
    except KeyError:
        raise UnknownSourceError(f"nenhum parser registrado para a fonte '{source}'") from None


__all__ = ["AlphaParser", "BetaParser", "ProductParser", "get_parser"]
