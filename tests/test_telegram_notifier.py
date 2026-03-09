from datetime import datetime, timezone

from app.models import NormalizedFields, RawListing, ScoredItem
from app.notifiers.telegram import TelegramNotifier


def _item() -> ScoredItem:
    return ScoredItem(
        raw=RawListing(
            source="mercari_public",
            item_url="https://jp.mercari.com/item/m123",
            title="iPhone 14 128GB SIMフリー",
            description="",
            listed_price=59000,
            shipping_fee=0,
            posted_at=None,
            seller_name="seller",
            image_urls=[],
            fetched_at=datetime.now(timezone.utc),
        ),
        normalized=NormalizedFields(
            model_name="iPhone 14",
            storage_gb=128,
            risk_flags=["network_restriction_unknown"],
            risk_score_breakdown={"network_restriction_unknown": 2},
            risk_score=2,
        ),
        expected_resale_price=76000,
        estimated_profit=6500,
        purchase_price=59000,
        selling_fee=7600,
        shipping_cost=750,
        risk_buffer=2150,
        resale_price_reasons=["base=76000(iPhone 14 128GB)"],
    )


def test_detailed_message_contains_breakdown_and_buyback_memo():
    item = _item()
    item.normalized.imei_candidates = ["356789012345678", "356789012345679"]
    notifier = TelegramNotifier(mode="detailed")
    msg = notifier.build_message(
        item,
        "notified_reason(profit>=3000, risk<=4, network_restriction_unknown)",
        buyback_snapshot={"buyback_floor": 27000, "floor_gap": -32000, "stale_quote_found": False},
    )
    assert "粗利根拠:" in msg
    assert "危険度スコア内訳:" in msg
    assert "IMEI件数: 2" in msg
    assert "先頭IMEI: 356789012345678" in msg
    assert "IMEI確認: https://naoseru.com/ja/imei-checker/" in msg
    assert "通知理由:" in msg
    assert "ネットワーク制限不明" in msg
    assert "想定粗利>=" in msg
    assert "危険度スコア<=" in msg
    assert "最悪出口: IOSYS下限 27,000円 / 現在価格差 -32,000円 / 最新" in msg


def test_concise_message_is_short_and_shows_missing_buyback_floor():
    notifier = TelegramNotifier(mode="concise")
    msg = notifier.build_message(
        _item(),
        "notified_reason(profit_current=6500,risk_threshold=4)",
        buyback_snapshot={"buyback_floor": None, "floor_gap": None, "stale_quote_found": False},
    )
    assert "粗利根拠:" not in msg
    assert "危険度スコア内訳:" not in msg
    assert "通知理由:" in msg
    assert "危険度スコア" in msg
    assert "最悪出口: buyback floor なし" in msg
    assert "IMEI件数:" not in msg
