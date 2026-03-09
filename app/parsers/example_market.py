from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.models import ListingLink, RawListing
from app.parsers.base import Parser
from app.utils.text import normalize_ws


class ExampleMarketParser(Parser):
    """Sample parser for a single marketplace.

    HTML assumptions are intentionally simple for MVP:
    - listing cards: .item-card
    - detail fields: semantic CSS classes
    """

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url

    def parse_listing(self, html: str) -> list[ListingLink]:
        soup = BeautifulSoup(html, "html.parser")
        links: list[ListingLink] = []
        cards = soup.select(".item-card, .product-card, li[data-item-id], article")
        for card in cards:
            a = _first_select(card, ["a.item-link", "a[href*='/item/']", "a[href]"])
            if not a or not a.get("href"):
                continue
            title = normalize_ws(a.get_text(" ", strip=True))
            price_text = _extract_price_text(card) or "0"
            listed_price = _to_yen(price_text)
            href = a["href"]
            url = urljoin(self.base_url, href) if self.base_url else href
            posted_at = None
            posted_el = _first_select(card, [".item-posted-at", ".posted-at", "time"])
            if posted_el:
                posted_at = normalize_ws(posted_el.get_text(" ", strip=True))
            links.append(ListingLink(url=url, title=title, listed_price=listed_price, posted_at=posted_at))
        return links

    def parse_item(
        self,
        source: str,
        item_url: str,
        html: str,
        notification_text: str | None = None,
    ) -> RawListing:
        soup = BeautifulSoup(html, "html.parser")
        title = _extract_title(soup)
        description = _extract_description(soup)
        listed_price = _to_yen(_extract_price_text(soup) or "0")
        shipping_text = _extract_shipping_text(soup) or "0"
        shipping_fee = _to_yen(shipping_text)
        posted_at = _extract_posted_at(soup)
        seller_name = _extract_seller_name(soup)
        image_urls = _extract_images(soup)
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
            notification_text=notification_text,
        )


def _to_yen(text: str) -> int:
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else 0


def _first_select(soup: BeautifulSoup, selectors: list[str]):
    for s in selectors:
        el = soup.select_one(s)
        if el is not None:
            return el
    return None


def _extract_title(soup: BeautifulSoup) -> str:
    el = _first_select(soup, ["h1.item-title", "h1", "meta[property='og:title']", "title"])
    if not el:
        return ""
    if el.name == "meta":
        return normalize_ws(el.get("content", ""))
    return normalize_ws(el.get_text(" ", strip=True))


def _extract_description(soup: BeautifulSoup) -> str:
    el = _first_select(
        soup,
        [
            ".item-description",
            "[data-description]",
            "meta[name='description']",
        ],
    )
    if not el:
        return ""
    if el.name == "meta":
        return normalize_ws(el.get("content", ""))
    return normalize_ws(el.get_text(" ", strip=True))


def _extract_price_text(soup: BeautifulSoup) -> str | None:
    el = _first_select(
        soup,
        [
            ".item-price",
            "[data-price]",
            ".price",
            "meta[property='product:price:amount']",
        ],
    )
    if el:
        if el.name == "meta":
            return normalize_ws(el.get("content", ""))
        if el.has_attr("data-price"):
            return normalize_ws(el["data-price"])
        return normalize_ws(el.get_text(" ", strip=True))
    data = _extract_json_ld(soup)
    offer = data.get("offers") if isinstance(data, dict) else None
    if isinstance(offer, dict):
        p = offer.get("price")
        return str(p) if p is not None else None
    return None


def _extract_shipping_text(soup: BeautifulSoup) -> str | None:
    el = _first_select(soup, [".item-shipping-fee", "[data-shipping-fee]", ".shipping-fee"])
    if not el:
        return None
    if el.has_attr("data-shipping-fee"):
        return normalize_ws(el["data-shipping-fee"])
    return normalize_ws(el.get_text(" ", strip=True))


def _extract_posted_at(soup: BeautifulSoup) -> str | None:
    el = _first_select(soup, [".item-posted-at", ".posted-at", "time"])
    if not el:
        return None
    if el.has_attr("datetime"):
        return normalize_ws(el["datetime"])
    return normalize_ws(el.get_text(" ", strip=True))


def _extract_seller_name(soup: BeautifulSoup) -> str | None:
    el = _first_select(soup, [".seller-name", ".shop-name", "[data-seller-name]"])
    if not el:
        return None
    if el.has_attr("data-seller-name"):
        return normalize_ws(el["data-seller-name"])
    return normalize_ws(el.get_text(" ", strip=True))


def _extract_images(soup: BeautifulSoup) -> list[str]:
    urls: list[str] = []
    for img in soup.select(".item-images img, .gallery img, img"):
        src = img.get("src") or img.get("data-src")
        if src:
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
                if isinstance(row, dict) and row.get("@type") in {"Product", "Offer"}:
                    return row
        if isinstance(data, dict):
            if data.get("@type") in {"Product", "Offer"}:
                return data
    return {}
