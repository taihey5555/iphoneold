from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Protocol

import requests


@dataclass
class FetchResult:
    url: str
    html: str


class MarketplaceFetcher(Protocol):
    def fetch(self, url: str, dynamic: bool = False) -> FetchResult:
        raise NotImplementedError


class ScraplingFetcher:
    """Scrapling adapter with conservative fallbacks.

    The application calls only this abstraction; direct Scrapling usage
    stays inside this class.
    """

    def __init__(self, timeout_seconds: int = 25) -> None:
        self.timeout_seconds = timeout_seconds
        self._scrapling = self._load_scrapling()

    def fetch(self, url: str, dynamic: bool = False) -> FetchResult:
        if self._scrapling is None:
            return self._requests_fetch(url)

        # Try several API shapes for compatibility across Scrapling versions.
        for method in (
            self._fetch_via_fetcher_classes,
            self._fetch_via_client_get,
            self._fetch_via_fetch_function,
            self._fetch_via_scraper_class,
        ):
            try:
                html = method(url, dynamic=dynamic)
            except Exception:
                html = None
            if html is not None:
                return FetchResult(url=url, html=html)
        return self._requests_fetch(url)

    def _fetch_via_fetcher_classes(self, url: str, dynamic: bool) -> str | None:
        mod = self._scrapling
        if not mod:
            return None
        if dynamic:
            dyn = getattr(mod, "DynamicFetcher", None)
            if dyn is None:
                return None
            resp = dyn.fetch(url)
            return self._extract_html(resp)
        stat = getattr(mod, "Fetcher", None)
        if stat is None:
            return None
        resp = stat.get(url)
        return self._extract_html(resp)

    def _load_scrapling(self):
        try:
            return importlib.import_module("scrapling")
        except Exception:
            return None

    def _fetch_via_client_get(self, url: str, dynamic: bool) -> str | None:
        mod = self._scrapling
        if not mod:
            return None
        client_cls = getattr(mod, "Client", None)
        if client_cls is None:
            return None
        client = client_cls(timeout=self.timeout_seconds)
        resp = client.get(url, dynamic=dynamic)
        return self._extract_html(resp)

    def _fetch_via_fetch_function(self, url: str, dynamic: bool) -> str | None:
        mod = self._scrapling
        if not mod:
            return None
        fn = getattr(mod, "fetch", None)
        if fn is None:
            return None
        resp = fn(url=url, dynamic=dynamic, timeout=self.timeout_seconds)
        return self._extract_html(resp)

    def _fetch_via_scraper_class(self, url: str, dynamic: bool) -> str | None:
        mod = self._scrapling
        if not mod:
            return None
        scraper_cls = getattr(mod, "Scraper", None)
        if scraper_cls is None:
            return None
        scraper = scraper_cls(dynamic=dynamic, timeout=self.timeout_seconds)
        resp = scraper.get(url)
        return self._extract_html(resp)

    def _requests_fetch(self, url: str) -> FetchResult:
        resp = requests.get(url, timeout=self.timeout_seconds)
        resp.raise_for_status()
        return FetchResult(url=url, html=resp.text)

    def _extract_html(self, resp) -> str | None:
        if resp is None:
            return None
        if isinstance(resp, str):
            return resp
        text = getattr(resp, "text", None)
        if isinstance(text, str) and text:
            return text
        html = getattr(resp, "html", None)
        if isinstance(html, str) and html:
            return html
        body = getattr(resp, "body", None)
        if isinstance(body, (bytes, bytearray)) and body:
            return body.decode("utf-8", errors="ignore")
        return None
