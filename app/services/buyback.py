from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.config import Settings
from app.models import ExitEvaluation
from app.repositories import ItemRepository


class BuybackEvaluationService:
    def __init__(self, settings: Settings, repository: ItemRepository) -> None:
        self.settings = settings
        self.repository = repository

    def evaluate_exit(
        self,
        source: str,
        item_url: str,
        item_category_override: str | None = None,
    ) -> ExitEvaluation:
        ctx = self.repository.get_item_buyback_context(source, item_url)
        if not ctx:
            raise ValueError(f"item not found: source={source} item_url={item_url}")

        item_category = item_category_override or ctx.get("item_category")
        shops = self.repository.list_buyback_shops(active_only=True)
        latest_quotes = self.repository.list_latest_buyback_quotes_by_shop(source, item_url)
        compatible_routes, incompatible_routes = _split_routes_by_category(shops, item_category)
        matching_quotes = _filter_quotes_for_category(item_category, latest_quotes)
        conservative_exit_price = compute_conservative_exit_price(item_category, latest_quotes)
        selected_quote = _select_best_quote_for_floor(matching_quotes)
        stale_quote_found = any(
            is_quote_stale(q.get("quote_checked_at"), self.settings.buyback.stale_quote_days) for q in matching_quotes
        )

        estimated_fees = int(self.settings.buyback.estimated_fee_yen)
        estimated_shipping_cost = int(self.settings.buyback.estimated_shipping_cost_yen)
        estimated_buyback_haircut = compute_estimated_buyback_haircut(selected_quote, self.settings)
        target_profit = int(self.settings.buyback.target_profit_yen)
        max_purchase_price = compute_max_purchase_price(
            conservative_exit_price=conservative_exit_price,
            estimated_fees=estimated_fees,
            estimated_shipping_cost=estimated_shipping_cost,
            estimated_buyback_haircut=estimated_buyback_haircut,
            target_profit=target_profit,
        )
        purchase_cost, purchase_cost_valid = _compute_purchase_cost(
            ctx.get("listed_price"),
            ctx.get("shipping_fee"),
        )
        decision = decide_exit_action(
            item_category=item_category,
            compatible_routes=compatible_routes,
            conservative_exit_price=conservative_exit_price,
            max_purchase_price=max_purchase_price,
            purchase_cost=purchase_cost,
            purchase_cost_valid=purchase_cost_valid,
            stale_quote_found=stale_quote_found,
            matching_quote_count=len(matching_quotes),
        )
        return ExitEvaluation(
            source=source,
            item_url=item_url,
            item_category=item_category,
            compatible_buyback_routes=compatible_routes,
            incompatible_buyback_routes=incompatible_routes,
            conservative_exit_price=conservative_exit_price,
            max_purchase_price=max_purchase_price,
            has_buyback_floor=conservative_exit_price is not None,
            decision=decision,
            risk_flags=list(ctx.get("risk_flags") or []),
            reason_summary=build_reason_summary(
                item_category=item_category,
                compatible_routes=compatible_routes,
                conservative_exit_price=conservative_exit_price,
                max_purchase_price=max_purchase_price,
                purchase_cost=purchase_cost,
                purchase_cost_valid=purchase_cost_valid,
                stale_quote_found=stale_quote_found,
                matching_quote_count=len(matching_quotes),
            ),
            estimated_fees=estimated_fees,
            estimated_shipping_cost=estimated_shipping_cost,
            estimated_buyback_haircut=estimated_buyback_haircut,
            target_profit=target_profit,
            stale_quote_found=stale_quote_found,
        )


def compute_conservative_exit_price(item_category: str | None, quotes: list[dict]) -> int | None:
    if not item_category:
        return None
    valid_quotes = _filter_quotes_for_category(item_category, quotes)
    if not valid_quotes:
        return None
    return max(int(q["quoted_price_min"]) for q in valid_quotes if q.get("quoted_price_min") is not None)


def compute_max_purchase_price(
    conservative_exit_price: int | None,
    estimated_fees: int,
    estimated_shipping_cost: int,
    estimated_buyback_haircut: int,
    target_profit: int,
) -> int | None:
    if conservative_exit_price is None:
        return None
    value = (
        int(conservative_exit_price)
        - int(estimated_fees)
        - int(estimated_shipping_cost)
        - int(estimated_buyback_haircut)
        - int(target_profit)
    )
    return max(0, value)


def compute_estimated_buyback_haircut(selected_quote: dict | None, settings: Settings) -> int:
    haircut = int(settings.buyback.default_haircut_yen)
    if selected_quote and selected_quote.get("supports_grade_pricing"):
        haircut += int(settings.buyback.grade_pricing_extra_haircut_yen)
    return haircut


def is_quote_stale(
    quote_checked_at: str | None,
    stale_quote_days: int,
    now: datetime | None = None,
) -> bool:
    if not quote_checked_at:
        return True
    current = now or datetime.now(timezone.utc)
    try:
        checked_at = datetime.fromisoformat(str(quote_checked_at).replace("Z", "+00:00"))
    except ValueError:
        return True
    threshold = current - timedelta(days=max(0, stale_quote_days))
    return checked_at < threshold


def decide_exit_action(
    item_category: str | None,
    compatible_routes: list[str],
    conservative_exit_price: int | None,
    max_purchase_price: int | None,
    purchase_cost: int | None,
    purchase_cost_valid: bool,
    stale_quote_found: bool,
    matching_quote_count: int,
) -> str:
    if not item_category:
        return "should_verify"
    if not compatible_routes:
        return "should_skip"
    if not purchase_cost_valid:
        return "should_verify"
    if conservative_exit_price is None:
        return "should_verify"
    if matching_quote_count <= 0:
        return "should_verify"
    if stale_quote_found:
        return "should_verify"
    if max_purchase_price is None or purchase_cost is None:
        return "should_verify"
    if purchase_cost <= max_purchase_price:
        return "should_buy"
    return "should_skip"


def build_reason_summary(
    item_category: str | None,
    compatible_routes: list[str],
    conservative_exit_price: int | None,
    max_purchase_price: int | None,
    purchase_cost: int | None,
    purchase_cost_valid: bool,
    stale_quote_found: bool,
    matching_quote_count: int,
) -> str:
    parts: list[str] = []
    if not item_category:
        parts.append("item_category未設定")
    if compatible_routes:
        parts.append(f"対応shop={len(compatible_routes)}")
    else:
        parts.append("対応shopなし")
    if conservative_exit_price is None:
        parts.append("buyback floorなし")
    else:
        parts.append(f"floor={conservative_exit_price:,}円")
    if max_purchase_price is not None:
        parts.append(f"max_purchase={max_purchase_price:,}円")
    if not purchase_cost_valid:
        parts.append("purchase_cost未確定")
    elif purchase_cost is not None:
        parts.append(f"purchase_cost={purchase_cost:,}円")
    if stale_quote_found:
        parts.append("stale quoteあり")
    if matching_quote_count <= 0 and item_category:
        parts.append("category一致quoteなし")
    return " / ".join(parts)


def _split_routes_by_category(shops: list[dict], item_category: str | None) -> tuple[list[str], list[str]]:
    compatible: list[str] = []
    incompatible: list[str] = []
    for shop in shops:
        if _shop_supports_category(shop, item_category):
            compatible.append(str(shop["shop_name"]))
        else:
            incompatible.append(str(shop["shop_name"]))
    return compatible, incompatible


def _filter_quotes_for_category(item_category: str | None, quotes: list[dict]) -> list[dict]:
    if not item_category:
        return []
    out: list[dict] = []
    for quote in quotes:
        if not quote.get("shop_is_active"):
            continue
        if quote.get("item_category") != item_category:
            continue
        if not _shop_supports_category(quote, item_category):
            continue
        if quote.get("quoted_price_min") is None:
            continue
        out.append(quote)
    return out


def _shop_supports_category(shop_or_quote: dict, item_category: str | None) -> bool:
    if not item_category:
        return False
    if item_category == "sealed":
        return bool(shop_or_quote.get("accepts_sealed"))
    if item_category == "opened_unused":
        return bool(shop_or_quote.get("accepts_opened_unused"))
    if item_category == "used":
        return bool(shop_or_quote.get("accepts_used"))
    return False


def _select_best_quote_for_floor(quotes: list[dict]) -> dict | None:
    if not quotes:
        return None
    return max(
        quotes,
        key=lambda q: (
            int(q.get("quoted_price_min") or 0),
            str(q.get("quote_checked_at") or ""),
            int(q.get("id") or 0),
        ),
    )


def _compute_purchase_cost(listed_price, shipping_fee) -> tuple[int | None, bool]:
    price = _coerce_int(listed_price)
    if price is None:
        return None, False
    shipping = _coerce_int(shipping_fee)
    return price + (shipping or 0), True


def _coerce_int(value) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None
