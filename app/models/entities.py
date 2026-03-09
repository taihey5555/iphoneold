from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


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
