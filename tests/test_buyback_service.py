from datetime import datetime, timedelta, timezone

from app.config import AppConfig, BuybackConfig, NotificationConfig, ScoringConfig, Settings
from app.models import CandidateItem, NormalizedFields, RawListing
from app.repositories import ItemRepository
from app.scoring import ProfitEstimator
from app.services.buyback import BuybackEvaluationService


def _settings(tmp_path):
    return Settings(
        app=AppConfig(
            timezone="Asia/Tokyo",
            min_profit_yen=3000,
            max_risk_score=4,
            duplicate_window_minutes=180,
            fetch_timeout_seconds=20,
            request_interval_seconds=0.0,
            use_dynamic_fetch=False,
            db_path=str(tmp_path / "test.db"),
            max_detail_per_listing_page=3,
            max_notifications_per_run=3,
            notification_mode="concise",
        ),
        scoring=ScoringConfig(),
        targets=[],
        sources=[],
        notification=NotificationConfig(),
        buyback=BuybackConfig(
            target_profit_yen=5000,
            estimated_shipping_cost_yen=750,
            estimated_fee_yen=0,
            default_haircut_yen=2000,
            grade_pricing_extra_haircut_yen=1000,
            stale_quote_days=14,
        ),
    )


def _insert_item(repo: ItemRepository, url: str, listed_price=50000, shipping_fee=0):
    raw = RawListing(
        source="mercari_public",
        item_url=url,
        title="iPhone 14 128GB",
        description="",
        listed_price=listed_price,
        shipping_fee=shipping_fee,
        posted_at=None,
        seller_name="seller",
        image_urls=[],
        fetched_at=datetime.now(timezone.utc),
    )
    item = CandidateItem(
        raw=raw,
        normalized=NormalizedFields(model_name="iPhone 14", storage_gb=128, risk_flags=["network_restriction_unknown"]),
        exclude_reason=None,
    )
    repo.upsert_scored_item(ProfitEstimator([]).score(item))


def test_evaluate_exit_uses_max_of_compatible_quote_mins(tmp_path):
    settings = _settings(tmp_path)
    repo = ItemRepository(settings.app.db_path)
    url = "https://jp.mercari.com/item/m1"
    _insert_item(repo, url, listed_price=50000)
    assert repo.update_item_category("mercari_public", url, "used")

    used_shop = repo.add_buyback_shop("UsedA", accepts_used=True)
    used_shop_2 = repo.add_buyback_shop("UsedB", accepts_used=True)
    opened_shop = repo.add_buyback_shop("OpenedOnly", accepts_used=False, accepts_opened_unused=True)
    repo.insert_buyback_quote("mercari_public", url, used_shop, "used", 61000, 65000, "B")
    repo.insert_buyback_quote("mercari_public", url, used_shop_2, "used", 63000, 68000, "A")
    repo.insert_buyback_quote("mercari_public", url, opened_shop, "opened_unused", 70000, 72000, "unused-opened")

    result = BuybackEvaluationService(settings, repo).evaluate_exit("mercari_public", url)

    assert result.conservative_exit_price == 63000
    assert result.max_purchase_price == 55250
    assert result.decision == "should_buy"
    assert "OpenedOnly" in result.incompatible_buyback_routes


def test_evaluate_exit_keeps_stale_quote_in_floor_but_marks_verify(tmp_path):
    settings = _settings(tmp_path)
    repo = ItemRepository(settings.app.db_path)
    url = "https://jp.mercari.com/item/m2"
    _insert_item(repo, url, listed_price=52000)
    assert repo.update_item_category("mercari_public", url, "used")

    shop_id = repo.add_buyback_shop("UsedA", accepts_used=True, supports_grade_pricing=True)
    stale_at = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    repo.insert_buyback_quote("mercari_public", url, shop_id, "used", 62000, 66000, "B", quote_checked_at=stale_at)

    result = BuybackEvaluationService(settings, repo).evaluate_exit("mercari_public", url)

    assert result.conservative_exit_price == 62000
    assert result.stale_quote_found is True
    assert result.decision == "should_verify"


def test_evaluate_exit_marks_verify_for_invalid_purchase_cost(tmp_path):
    settings = _settings(tmp_path)
    repo = ItemRepository(settings.app.db_path)
    url = "https://jp.mercari.com/item/m3"
    _insert_item(repo, url, listed_price=50000)
    assert repo.update_item_category("mercari_public", url, "used")

    shop_id = repo.add_buyback_shop("UsedA", accepts_used=True)
    repo.insert_buyback_quote("mercari_public", url, shop_id, "used", 65000, 67000, "B")

    conn = repo._connect()
    conn.execute("UPDATE items SET listed_price = ? WHERE source = ? AND item_url = ?", ("bad", "mercari_public", url))
    conn.commit()
    conn.close()

    result = BuybackEvaluationService(settings, repo).evaluate_exit("mercari_public", url)

    assert result.conservative_exit_price == 65000
    assert result.decision == "should_verify"


def test_latest_buyback_quote_by_shop_uses_id_tiebreak(tmp_path):
    settings = _settings(tmp_path)
    repo = ItemRepository(settings.app.db_path)
    url = "https://jp.mercari.com/item/m4"
    _insert_item(repo, url, listed_price=50000)
    shop_id = repo.add_buyback_shop("UsedA", accepts_used=True)
    checked_at = datetime.now(timezone.utc).isoformat()
    repo.insert_buyback_quote("mercari_public", url, shop_id, "used", 60000, quote_checked_at=checked_at)
    repo.insert_buyback_quote("mercari_public", url, shop_id, "used", 62000, quote_checked_at=checked_at)

    rows = repo.list_latest_buyback_quotes_by_shop("mercari_public", url)

    assert len(rows) == 1
    assert rows[0]["quoted_price_min"] == 62000
