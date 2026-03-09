from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_IOSYS_CARD_PATTERN = re.compile(
    r"^(?P<carrier>.+?)\s+"
    r"(?P<model>iPhone.+?)\s+"
    r"(?P<storage>\d+\s*(?:GB|TB))\s+"
    r"未使用品買取価格\s*(?P<opened>[\d,]+)円\s+"
    r"中古買取価格\s*(?P<used_min>[\d,]+)円(?:\s*[~～]\s*(?P<used_max>[\d,]+)円)?$",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class IosysBuybackQuoteRow:
    model_name_raw: str
    model_name_key: str
    carrier_type: str
    storage_gb: int
    item_category: str
    quoted_price_min: int
    quoted_price_max: int
    source_url: str
    quote_checked_at: str


@dataclass(frozen=True)
class IosysBuybackParseResult:
    rows: list[IosysBuybackQuoteRow]
    error_count: int = 0


class IosysBuybackParser:
    def parse_quotes(self, html: str, source_url: str, quote_checked_at: str | None = None) -> IosysBuybackParseResult:
        checked_at = quote_checked_at or datetime.now(timezone.utc).isoformat()
        soup = BeautifulSoup(html, "html.parser")
        rows: list[IosysBuybackQuoteRow] = []
        error_count = 0

        for table in soup.find_all("table"):
            header_map = _build_header_map(table)
            if header_map:
                for tr in table.find_all("tr"):
                    cells = tr.find_all(["td", "th"])
                    if not cells or tr.find("th") is not None:
                        continue
                    try:
                        rows.extend(_parse_header_row(cells, header_map, source_url, checked_at))
                    except ValueError as exc:
                        logger.warning("iosys parser skipped header row: err=%s row=%s", exc, tr.get_text(" ", strip=True))
                        error_count += 1
                continue

            card_rows, card_errors = _parse_card_table(table, source_url, checked_at)
            rows.extend(card_rows)
            error_count += card_errors

        return IosysBuybackParseResult(rows=rows, error_count=error_count)


def normalize_model_name(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = re.sub(r"[\(\（][^\)\）]*[\)\）]", " ", text)
    text = re.sub(r"\bapple\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"iphone\s*(\d{1,2}[a-z]?)", r"iPhone \1", text, flags=re.IGNORECASE)
    text = re.sub(r"(\d)(pro max|promax|pro|plus|mini)\b", r"\1 \2", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(promax)\b", "pro max", text, flags=re.IGNORECASE)
    text = re.sub(r"\bpro\s*max\b", "pro max", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(plus|mini|pro)\b", lambda m: m.group(1).lower(), text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:1\s*tb|64|128|256|512|1024)\s*(?:gb|tb)?\b", " ", text, flags=re.IGNORECASE)
    for token in ("docomo", "au", "softbank", "rakuten", "ymobile", "y!mobile", "uqmobile", "国内版", "海外版"):
        text = re.sub(re.escape(token), " ", text, flags=re.IGNORECASE)
    text = re.sub(r"(sim\s*free|simフリー)", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"(ミッドナイト|スターライト|ブラック|ホワイト|ブルー|パープル|レッド)", " ", text)
    text = re.sub(r"[/_-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def normalize_carrier_type(value: str) -> str | None:
    text = _normalize_text(value).replace(" ", "")
    if not text:
        return None
    if "uqmobile" in text or "uq" in text:
        return "au"
    if "ymobile" in text or "y!mobile" in text:
        return "softbank"
    if "docomo" in text:
        return "docomo"
    if re.search(r"(^|[^a-z])au($|[^a-z])", _normalize_text(value)):
        return "au"
    if "softbank" in text:
        return "softbank"
    if "rakuten" in text:
        return "rakuten"
    if "simフリー" in text or "simfree" in text or "国内版" in text or "海外版" in text:
        return "sim_free"
    return None


def map_iosys_item_category(label: str) -> str | None:
    text = unicodedata.normalize("NFKC", str(label or "")).strip()
    if text == "未使用":
        return "opened_unused"
    if text == "中古":
        return "used"
    return None


def extract_storage_gb(text: str) -> int | None:
    normalized = _normalize_text(text)
    match = re.search(r"(\d{1,4})\s*(gb|tb)\b", normalized, flags=re.IGNORECASE)
    if not match:
        return None
    value = int(match.group(1))
    unit = match.group(2).lower()
    if unit == "tb":
        value *= 1024
    return value


def _build_header_map(table) -> dict[str, int]:
    for tr in table.find_all("tr"):
        headers = tr.find_all("th")
        if not headers:
            continue
        header_map: dict[str, int] = {}
        for idx, cell in enumerate(headers):
            text = unicodedata.normalize("NFKC", cell.get_text(" ", strip=True))
            if "機種" in text or "モデル" in text:
                header_map["model"] = idx
            elif "容量" in text:
                header_map["storage"] = idx
            elif "キャリア" in text:
                header_map["carrier"] = idx
            elif "未使用" in text:
                header_map["opened_unused"] = idx
            elif "中古" in text:
                header_map["used"] = idx
        if {"model", "storage", "carrier"} <= set(header_map):
            return header_map
    return {}


def _parse_header_row(cells, header_map: dict[str, int], source_url: str, quote_checked_at: str) -> list[IosysBuybackQuoteRow]:
    def cell_text(name: str) -> str:
        idx = header_map.get(name)
        if idx is None or idx >= len(cells):
            return ""
        return cells[idx].get_text(" ", strip=True)

    model_name_raw = cell_text("model")
    model_name_key = normalize_model_name(model_name_raw)
    if not model_name_key:
        raise ValueError("missing model name")

    storage_gb = extract_storage_gb(cell_text("storage"))
    if storage_gb is None:
        raise ValueError("missing storage")

    carrier_type = normalize_carrier_type(cell_text("carrier"))
    if carrier_type is None:
        raise ValueError("missing carrier")

    rows: list[IosysBuybackQuoteRow] = []
    for header_name, category_label in (("opened_unused", "未使用"), ("used", "中古")):
        value = cell_text(header_name)
        item_category = map_iosys_item_category(category_label)
        if item_category is None or not value or value in {"-", "--"}:
            continue
        price_min, price_max = _parse_price_range(value)
        rows.append(
            IosysBuybackQuoteRow(
                model_name_raw=model_name_raw,
                model_name_key=model_name_key,
                carrier_type=carrier_type,
                storage_gb=storage_gb,
                item_category=item_category,
                quoted_price_min=price_min,
                quoted_price_max=price_max,
                source_url=source_url,
                quote_checked_at=quote_checked_at,
            )
        )
    return rows


def _parse_card_table(table, source_url: str, quote_checked_at: str) -> tuple[list[IosysBuybackQuoteRow], int]:
    normalized = _normalize_text(table.get_text(" ", strip=True))
    if not normalized or "未使用品買取価格" not in normalized or "中古買取価格" not in normalized:
        return [], 0

    rows: list[IosysBuybackQuoteRow] = []
    error_count = 0
    for segment in _split_iosys_segments(normalized):
        match = _IOSYS_CARD_PATTERN.match(segment)
        if not match:
            logger.warning("iosys parser skipped card segment: err=pattern_mismatch text=%s", segment[:300])
            error_count += 1
            continue

        model_name_raw = match.group("model").strip()
        model_name_key = normalize_model_name(model_name_raw)
        storage_gb = extract_storage_gb(match.group("storage"))
        carrier_type = normalize_carrier_type(match.group("carrier"))
        if not model_name_key or storage_gb is None or carrier_type is None:
            logger.warning("iosys parser skipped card segment: err=missing_model_storage_or_carrier text=%s", segment[:300])
            error_count += 1
            continue

        opened_price = _parse_price(match.group("opened"))
        used_min = _parse_price(match.group("used_min"))
        used_max = _parse_price(match.group("used_max")) if match.group("used_max") else used_min

        rows.append(
            IosysBuybackQuoteRow(
                model_name_raw=model_name_raw,
                model_name_key=model_name_key,
                carrier_type=carrier_type,
                storage_gb=storage_gb,
                item_category="opened_unused",
                quoted_price_min=opened_price,
                quoted_price_max=opened_price,
                source_url=source_url,
                quote_checked_at=quote_checked_at,
            )
        )
        rows.append(
            IosysBuybackQuoteRow(
                model_name_raw=model_name_raw,
                model_name_key=model_name_key,
                carrier_type=carrier_type,
                storage_gb=storage_gb,
                item_category="used",
                quoted_price_min=min(used_min, used_max),
                quoted_price_max=max(used_min, used_max),
                source_url=source_url,
                quote_checked_at=quote_checked_at,
            )
        )
    return rows, error_count


def _split_iosys_segments(text: str) -> list[str]:
    segments = []
    for part in re.split(r"申込みは\s*こちら", text):
        segment = part.strip()
        if segment and "買取価格" in segment:
            segments.append(segment)
    return segments


def _parse_price(value: str) -> int:
    return int(str(value).replace(",", ""))


def _parse_price_range(value: str) -> tuple[int, int]:
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    nums = [int(raw.replace(",", "")) for raw in re.findall(r"\d[\d,]*", normalized)]
    if not nums:
        raise ValueError(f"missing price: {value}")
    if len(nums) == 1:
        return nums[0], nums[0]
    return min(nums), max(nums)


def _normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()
