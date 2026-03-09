from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

BUYBACK_ITEM_CATEGORIES = ("sealed", "opened_unused", "used")
BUYBACK_DECISIONS = ("should_buy", "should_skip", "should_verify")


@dataclass
class ListingLink:
    url: str
    title: str
    listed_price: int
    posted_at: str | None = None


@dataclass
class RawListing:
    source: str
    item_url: str
    title: str
    description: str
    listed_price: int
    shipping_fee: int
    posted_at: str | None
    seller_name: str | None
    image_urls: list[str]
    fetched_at: datetime
    notification_text: str | None = None


@dataclass
class NormalizedFields:
    model_name: str | None = None
    storage_gb: int | None = None
    color: str | None = None
    carrier: str | None = None
    sim_free_flag: bool | None = None
    battery_health: int | None = None
    network_restriction_status: str | None = None
    condition_flags: list[str] = field(default_factory=list)
    repair_history_flag: bool | None = None
    face_id_flag: bool | None = None
    camera_issue_flag: bool | None = None
    screen_issue_flag: bool | None = None
    activation_issue_flag: bool | None = None
    accessories_flags: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    risk_score: int = 0
    risk_score_breakdown: dict[str, int] = field(default_factory=dict)


@dataclass
class SourceItem:
    raw: RawListing
    normalized: NormalizedFields


@dataclass
class CandidateItem(SourceItem):
    exclude_reason: str | None = None


@dataclass
class ScoredItem(CandidateItem):
    expected_resale_price: int = 0
    estimated_profit: int = 0
    purchase_price: int = 0
    selling_fee: int = 0
    shipping_cost: int = 0
    risk_buffer: int = 0
    resale_price_reasons: list[str] = field(default_factory=list)
    notification_reason: str | None = None


@dataclass
class BuybackShop:
    id: int | None = None
    shop_name: str = ""
    accepts_sealed: bool = False
    accepts_opened_unused: bool = False
    accepts_used: bool = True
    supports_grade_pricing: bool = False
    supports_junk: bool = False
    notes: str | None = None
    is_active: bool = True


@dataclass
class BuybackQuote:
    id: int | None = None
    source: str = ""
    item_url: str = ""
    shop_id: int = 0
    item_category: str = "used"
    quoted_price_min: int = 0
    quoted_price_max: int | None = None
    condition_assumption: str | None = None
    quote_checked_at: str = ""
    source_url: str | None = None
    notes: str | None = None


@dataclass
class ExitEvaluation:
    source: str
    item_url: str
    item_category: str | None
    compatible_buyback_routes: list[str]
    incompatible_buyback_routes: list[str]
    conservative_exit_price: int | None
    max_purchase_price: int | None
    has_buyback_floor: bool
    decision: str
    risk_flags: list[str]
    reason_summary: str
    estimated_fees: int
    estimated_shipping_cost: int
    estimated_buyback_haircut: int
    target_profit: int
    stale_quote_found: bool
