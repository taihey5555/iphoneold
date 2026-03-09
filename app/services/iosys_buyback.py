from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field

from app.parsers.iosys_buyback import IosysBuybackParser, IosysBuybackQuoteRow, normalize_model_name
from app.repositories import ItemRepository, MarketplaceFetcher

logger = logging.getLogger(__name__)
UNMATCHED_SAMPLE_LIMIT = 5


@dataclass(frozen=True)
class IosysUnmatchedExample:
    model_name_raw: str
    carrier_type: str
    storage_gb: int
    item_category: str
    reason: str


@dataclass(frozen=True)
class IosysBuybackFetchSummary:
    saved_count: int = 0
    skipped_count: int = 0
    unmatched_quote_rows: int = 0
    expanded_item_count: int = 0
    parser_error_count: int = 0
    insert_error_count: int = 0
    item_category_missing_count: int = 0
    unmatched_reason_counts: dict[str, int] = field(default_factory=dict)
    unmatched_examples: list[IosysUnmatchedExample] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["unmatched_examples"] = [asdict(example) for example in self.unmatched_examples]
        return payload


class IosysBuybackService:
    def __init__(self, fetcher: MarketplaceFetcher, repository: ItemRepository, parser: IosysBuybackParser | None = None) -> None:
        self.fetcher = fetcher
        self.repository = repository
        self.parser = parser or IosysBuybackParser()

    def fetch_and_store(self, source_url: str) -> IosysBuybackFetchSummary:
        result = self.fetcher.fetch(source_url, dynamic=False)
        parsed = self.parser.parse_quotes(result.html, source_url=source_url)
        shop_id = self._resolve_iosys_shop_id()
        summary = IosysBuybackFetchSummary(parser_error_count=parsed.error_count)
        messages = list(summary.messages)
        saved_count = 0
        skipped_count = 0
        unmatched_quote_rows = 0
        expanded_item_count = 0
        insert_error_count = 0
        item_category_missing_count = 0
        unmatched_reason_counts: dict[str, int] = {}
        unmatched_examples: list[IosysUnmatchedExample] = []

        for row in parsed.rows:
            matches, unmatched_reason = self._match_items(row)
            if not matches:
                unmatched_quote_rows += 1
                unmatched_reason_counts[unmatched_reason] = unmatched_reason_counts.get(unmatched_reason, 0) + 1
                if unmatched_reason == "item_category_missing":
                    item_category_missing_count += 1
                if len(unmatched_examples) < UNMATCHED_SAMPLE_LIMIT:
                    unmatched_examples.append(
                        IosysUnmatchedExample(
                            model_name_raw=row.model_name_raw,
                            carrier_type=row.carrier_type,
                            storage_gb=row.storage_gb,
                            item_category=row.item_category,
                            reason=unmatched_reason,
                        )
                    )
                logger.info(
                    "iosys quote row unmatched: model=%s carrier=%s storage=%s category=%s reason=%s",
                    row.model_name_raw,
                    row.carrier_type,
                    row.storage_gb,
                    row.item_category,
                    unmatched_reason,
                )
                continue

            expanded_item_count += len(matches)
            for item in matches:
                latest = self.repository.get_latest_buyback_quote_for_item_shop(
                    source=item["source"],
                    item_url=item["item_url"],
                    shop_id=shop_id,
                )
                notes = _build_iosys_notes(row)
                if _same_quote(latest, row):
                    skipped_count += 1
                    continue
                try:
                    self.repository.insert_buyback_quote(
                        source=item["source"],
                        item_url=item["item_url"],
                        shop_id=shop_id,
                        item_category=row.item_category,
                        quoted_price_min=row.quoted_price_min,
                        quoted_price_max=row.quoted_price_max,
                        condition_assumption=None,
                        source_url=row.source_url,
                        notes=notes,
                        quote_checked_at=row.quote_checked_at,
                    )
                    saved_count += 1
                except Exception as exc:
                    insert_error_count += 1
                    msg = (
                        f"insert failed: source={item['source']} item_url={item['item_url']} "
                        f"model={row.model_name_raw} carrier={row.carrier_type} storage={row.storage_gb} err={exc}"
                    )
                    messages.append(msg)
                    logger.exception(msg)

        return IosysBuybackFetchSummary(
            saved_count=saved_count,
            skipped_count=skipped_count,
            unmatched_quote_rows=unmatched_quote_rows,
            expanded_item_count=expanded_item_count,
            parser_error_count=parsed.error_count,
            insert_error_count=insert_error_count,
            item_category_missing_count=item_category_missing_count,
            unmatched_reason_counts=unmatched_reason_counts,
            unmatched_examples=unmatched_examples,
            messages=messages,
        )

    def _resolve_iosys_shop_id(self) -> int:
        shop_id = self.repository.resolve_buyback_shop_id("IOSYS")
        if shop_id is not None:
            return shop_id
        return self.repository.add_buyback_shop(
            shop_name="IOSYS",
            accepts_opened_unused=True,
            accepts_used=True,
            supports_grade_pricing=True,
            notes="auto-created for iosys fetch",
        )

    def _match_items(self, row: IosysBuybackQuoteRow) -> tuple[list[dict], str | None]:
        storage_candidates = self.repository.find_iosys_buyback_candidates(
            carrier_type=row.carrier_type,
            storage_gb=row.storage_gb,
        )
        if not storage_candidates:
            storage_only = self.repository.find_iosys_buyback_candidates_for_storage(storage_gb=row.storage_gb)
            if not storage_only:
                return [], "no_candidate_by_storage"
            return [], "no_candidate_by_carrier"

        model_candidates = []
        for candidate in storage_candidates:
            current_model_key = candidate["normalized"].get("model_name") or ""
            if normalize_model_name(current_model_key) == row.model_name_key:
                model_candidates.append(candidate)
        if not model_candidates:
            return [], "model_name_mismatch"

        matches = [candidate for candidate in model_candidates if candidate.get("item_category") == row.item_category]
        if matches:
            return matches, None

        missing_category = [
            candidate
            for candidate in model_candidates
            if candidate.get("item_category") in (None, "")
        ]
        if missing_category:
            return [], "item_category_missing"
        return [], "item_category_mismatch"


def _same_quote(latest: dict | None, row: IosysBuybackQuoteRow) -> bool:
    if not latest:
        return False
    return (
        latest.get("item_category") == row.item_category
        and int(latest.get("quoted_price_min") or 0) == row.quoted_price_min
        and _normalize_nullable_int(latest.get("quoted_price_max")) == row.quoted_price_max
        and latest.get("condition_assumption") is None
        and (latest.get("source_url") or None) == row.source_url
    )


def _normalize_nullable_int(value) -> int | None:
    if value is None:
        return None
    return int(value)


def _build_iosys_notes(row: IosysBuybackQuoteRow) -> str:
    return f"iosys:auto:model={row.model_name_raw};carrier={row.carrier_type};storage={row.storage_gb}"
