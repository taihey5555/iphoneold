from datetime import datetime, timezone

from app.models import CandidateItem, NormalizedFields, RawListing
from app.repositories.item_repository import ItemRepository
from app.scoring import ProfitEstimator
from app.services.monitor import MonitorService


def test_recent_notification_by_url(tmp_path):
    repo = ItemRepository(str(tmp_path / "test.db"))
    repo.mark_notified("example_market", "https://example.com/item/1", dedupe_key="k1")
    assert repo.has_recent_notification(
        source="example_market",
        item_url="https://example.com/item/1",
        window_minutes=60,
        dedupe_key="k1",
    )


def test_recent_notification_by_dedupe_key(tmp_path):
    repo = ItemRepository(str(tmp_path / "test.db"))
    repo.mark_notified("example_market", "https://example.com/item/1", dedupe_key="same-key")
    assert repo.has_recent_notification(
        source="example_market",
        item_url="https://example.com/item/2",
        window_minutes=60,
        dedupe_key="same-key",
    )


def test_recent_notification_by_similarity_key(tmp_path):
    repo = ItemRepository(str(tmp_path / "test.db"))
    repo.mark_notified("example_market", "https://example.com/item/1", dedupe_key="k1", similarity_key="sim-a")
    assert repo.has_recent_notification(
        source="example_market",
        item_url="https://example.com/item/other",
        window_minutes=60,
        dedupe_key="k-other",
        similarity_key="sim-a",
    )


def test_dedupe_key_generation_shape():
    item = CandidateItem(
        raw=RawListing(
            source="example_market",
            item_url="https://example.com/item/1",
            title="iPhone 14 128GB",
            description="",
            listed_price=59800,
            shipping_fee=800,
            posted_at=None,
            seller_name="alice",
            image_urls=[],
            fetched_at=datetime.now(timezone.utc),
        ),
        normalized=NormalizedFields(model_name="iPhone 14", storage_gb=128),
        exclude_reason=None,
    )
    key = MonitorService._dedupe_key(item)
    assert key == "example_market|iPhone 14|128|60000|alice"


def test_item_review_status_default_and_update(tmp_path):
    repo = ItemRepository(str(tmp_path / "test.db"))
    raw = RawListing(
        source="example_market",
        item_url="https://example.com/item/1",
        title="iPhone 14 128GB",
        description="",
        listed_price=50000,
        shipping_fee=0,
        posted_at=None,
        seller_name="alice",
        image_urls=[],
        fetched_at=datetime.now(timezone.utc),
    )
    item = CandidateItem(raw=raw, normalized=NormalizedFields(model_name="iPhone 14", storage_gb=128), exclude_reason=None)
    scored = ProfitEstimator([]).score(item)
    repo.upsert_scored_item(scored)
    import sqlite3

    conn = sqlite3.connect(str(tmp_path / "test.db"))
    before = conn.execute("SELECT review_status, review_note FROM items WHERE source=? AND item_url=?", ("example_market", "https://example.com/item/1")).fetchone()
    assert before and before[0] == "pending"
    repo.update_review_status("example_market", "https://example.com/item/1", "watched", review_note="battery 80-84%")
    after = conn.execute("SELECT review_status, review_note FROM items WHERE source=? AND item_url=?", ("example_market", "https://example.com/item/1")).fetchone()
    assert after and after[0] == "watched"
    assert after and after[1] == "battery 80-84%"


def test_item_outcome_update_computes_actual_profit(tmp_path):
    repo = ItemRepository(str(tmp_path / "test.db"))
    raw = RawListing(
        source="example_market",
        item_url="https://example.com/item/2",
        title="iPhone 14 128GB",
        description="",
        listed_price=50000,
        shipping_fee=800,
        posted_at=None,
        seller_name="alice",
        image_urls=[],
        fetched_at=datetime.now(timezone.utc),
    )
    item = CandidateItem(raw=raw, normalized=NormalizedFields(model_name="iPhone 14", storage_gb=128), exclude_reason=None)
    scored = ProfitEstimator([]).score(item)
    repo.upsert_scored_item(scored)

    assert repo.update_outcome(
        "example_market",
        "https://example.com/item/2",
        "buyback_done",
        exit_channel="buyback_shop",
        actual_sale_price=56000,
        outcome_note="same day",
    )

    import sqlite3

    conn = sqlite3.connect(str(tmp_path / "test.db"))
    row = conn.execute(
        "SELECT exit_channel, outcome_status, actual_sale_price, actual_profit, outcome_note FROM items WHERE source=? AND item_url=?",
        ("example_market", "https://example.com/item/2"),
    ).fetchone()
    assert row == ("buyback_shop", "buyback_done", 56000, 5200, "same day")
