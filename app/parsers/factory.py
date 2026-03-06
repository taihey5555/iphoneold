from __future__ import annotations

from urllib.parse import urlparse

from app.parsers.base import Parser
from app.parsers.example_market import ExampleMarketParser
from app.parsers.mercari_public import MercariPublicParser


def build_parser(name: str, sample_url: str | None = None) -> Parser:
    if name == "example_market":
        base_url = None
        if sample_url:
            parsed = urlparse(sample_url)
            base_url = f"{parsed.scheme}://{parsed.netloc}"
        return ExampleMarketParser(base_url=base_url)
    if name == "mercari_public":
        return MercariPublicParser()
    raise ValueError(f"Unsupported parser: {name}")
