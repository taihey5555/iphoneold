from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from app.models import ListingLink, RawListing
from app.parsers.base import Parser
from app.utils.text import normalize_ws

MERCARI_HOST = "jp.mercari.com"
MERCARI_ALLOWED_LISTING_PATHS = {"/search"}
MERCARI_ALLOWED_ITEM_PATH_PREFIX = "/item/"
MERCARI_BLOCKED_PATH_PREFIXES = ("/purchase", "/sell", "/mypage", "/transaction", "/v1", "/v2")


class MercariPublicParser(Parser):
    """Parser limited to Mercari public search and public item pages."""

    def __init__(self, base_url: str = "https://jp.mercari.com") -> None:
        self.base_url = base_url

    def is_allowed_listing_url(self, url: str) -> bool:
        parsed = urlparse(url)
        return parsed.netloc == MERCARI_HOST and parsed.path in MERCARI_ALLOWED_LISTING_PATHS

    def is_allowed_item_url(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.netloc != MERCARI_HOST:
            return False
        if any(parsed.path.startswith(p) for p in MERCARI_BLOCKED_PATH_PREFIXES):
            return False
        return parsed.path.startswith(MERCARI_ALLOWED_ITEM_PATH_PREFIX)

    def parse_listing(self, html: str) -> list[ListingLink]:
        soup = BeautifulSoup(html, "html.parser")
        out: list[ListingLink] = []
        seen: set[str] = set()

        for a in soup.select("a[href*='/item/m']"):
            href = a.get("href")
            if not href:
                continue
            url = urljoin(self.base_url, href)
            if not self.is_allowed_item_url(url) or url in seen:
                continue
            seen.add(url)
            text = normalize_ws(a.get_text(" ", strip=True))
            title = text.split("¥")[0].strip() if "¥" in text else text
            price = _extract_price_from_text(text)
            out.append(ListingLink(url=url, title=title or "Mercari item", listed_price=price, posted_at=None))
        return out

    def parse_item(self, source: str, item_url: str, html: str) -> RawListing:
        soup = BeautifulSoup(html, "html.parser")
        title = _extract_title(soup)
        description = _extract_description(soup)
        listed_price = _extract_price(soup)
        shipping_fee = _extract_shipping_fee(soup)
        seller_name = _extract_seller_name(soup)
        image_urls = _extract_images(soup)
        posted_at = _extract_posted_at(soup)
        return RawListing(
            source=source,
            item_url=item_url,
            title=title,
            description=description,
            listed_price=listed_price,
            shipping_fee=shipping_fee,
            posted_at=posted_at,
            seller_name=seller_name,
            image_urls=image_urls,
            fetched_at=datetime.now(timezone.utc),
        )


def _extract_title(soup: BeautifulSoup) -> str:
    og = soup.select_one("meta[property='og:title']")
    if og and og.get("content"):
        return normalize_ws(og["content"])
    h1 = soup.select_one("h1")
    if h1:
        return normalize_ws(h1.get_text(" ", strip=True))
    return ""


def _extract_description(soup: BeautifulSoup) -> str:
    meta = soup.select_one("meta[name='description']")
    if meta and meta.get("content"):
        return normalize_ws(meta["content"])
    for el in soup.select("[data-testid*='description'], .item-description"):
        text = normalize_ws(el.get_text(" ", strip=True))
        if text:
            return text
    data = _extract_json_ld(soup)
    desc = data.get("description") if isinstance(data, dict) else None
    return normalize_ws(str(desc)) if desc else ""


def _extract_price(soup: BeautifulSoup) -> int:
    for el in soup.select("meta[property='product:price:amount'], [data-testid*='price'], .item-price"):
        if el.name == "meta":
            text = normalize_ws(el.get("content", ""))
        else:
            text = normalize_ws(el.get_text(" ", strip=True))
        value = _extract_price_from_text(text)
        if value > 0:
            return value
    data = _extract_json_ld(soup)
    offers = data.get("offers") if isinstance(data, dict) else None
    if isinstance(offers, dict) and offers.get("price") is not None:
        return _extract_price_from_text(str(offers.get("price")))
    return 0


def _extract_shipping_fee(soup: BeautifulSoup) -> int:
    for el in soup.select("[data-testid*='shipping'], .item-shipping-fee"):
        text = normalize_ws(el.get_text(" ", strip=True))
        if "送料込み" in text:
            return 0
        value = _extract_price_from_text(text)
        if value > 0:
            return value
    return 0


def _extract_seller_name(soup: BeautifulSoup) -> str | None:
    for el in soup.select("[data-testid*='seller'], .seller-name"):
        text = normalize_ws(el.get_text(" ", strip=True))
        if text:
            return text
    return None


def _extract_images(soup: BeautifulSoup) -> list[str]:
    urls: list[str] = []
    for img in soup.select("img"):
        src = img.get("src") or img.get("data-src")
        if src and src.startswith("http"):
            urls.append(src)
    if urls:
        return urls
    data = _extract_json_ld(soup)
    images = data.get("image") if isinstance(data, dict) else None
    if isinstance(images, list):
        return [str(x) for x in images]
    if isinstance(images, str):
        return [images]
    return []


def _extract_posted_at(soup: BeautifulSoup) -> str | None:
    time_el = soup.select_one("time")
    if time_el:
        if time_el.has_attr("datetime"):
            return normalize_ws(time_el["datetime"])
        text = normalize_ws(time_el.get_text(" ", strip=True))
        if text:
            return text
    return None


def _extract_json_ld(soup: BeautifulSoup) -> dict:
    for script in soup.select("script[type='application/ld+json']"):
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        if isinstance(data, list):
            for row in data:
                if isinstance(row, dict) and row.get("@type") == "Product":
                    return row
        if isinstance(data, dict) and data.get("@type") == "Product":
            return data
    return {}


def _extract_price_from_text(text: str) -> int:
    raw = text or ""
    m = re.search(r"(?:¥|￥)\s*(\d[\d,]*)", raw)
    if m:
        return int(m.group(1).replace(",", ""))
    values = [int(x.replace(",", "")) for x in re.findall(r"\d[\d,]*", raw)]
    if not values:
        return 0
    candidates = [v for v in values if v >= 1000]
    return max(candidates) if candidates else max(values)
