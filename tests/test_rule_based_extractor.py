from datetime import datetime, timezone

from app.extractors.rule_based import RISK_SCORE_WEIGHTS, RuleBasedExtractor
from app.models import RawListing


def _raw(title: str, desc: str) -> RawListing:
    return RawListing(
        source="example_market",
        item_url="https://example.com/item/1",
        title=title,
        description=desc,
        listed_price=50000,
        shipping_fee=1000,
        posted_at=None,
        seller_name="seller_a",
        image_urls=[],
        fetched_at=datetime.now(timezone.utc),
    )


def test_normalization_extracts_main_fields():
    item = _raw(
        "iPhone 14 128GB ミッドナイト SIMフリー",
        "docomo購入 バッテリー 91% 判定○",
    )
    norm = RuleBasedExtractor().extract(item)
    assert norm.model_name == "iPhone 14"
    assert norm.storage_gb == 128
    assert norm.color == "ミッドナイト"
    assert norm.sim_free_flag is True
    assert norm.battery_health == 91
    assert norm.network_restriction_status == "ok"


def test_risk_word_detection_and_score_table():
    item = _raw(
        "iPhone 13 128GB",
        "face id不可 非純正ディスプレイ 充電不良 修理歴あり アクティベーションロック",
    )
    norm = RuleBasedExtractor().extract(item)
    expected_flags = {
        "face_id_not_working",
        "non_genuine_display",
        "charging_issue",
        "repair_history",
        "activation_lock_risk",
        "network_restriction_unknown",
    }
    assert expected_flags.issubset(set(norm.risk_flags))
    expected_score = sum(RISK_SCORE_WEIGHTS[f] for f in expected_flags)
    assert norm.risk_score == expected_score


def test_variant_models_are_not_downgraded_to_base_model():
    item = _raw(
        "iPhone 15 Plus 128GB SIMフリー",
        "軽い曲がりあり 画面交換済み 非純正品",
    )
    norm = RuleBasedExtractor().extract(item)
    assert norm.model_name == "iPhone 15 Plus"
    assert "frame_damage" in norm.risk_flags
    assert "non_genuine_display" in norm.risk_flags
    assert norm.repair_history_flag is True


def test_face_id_defaults_to_unknown_without_positive_or_negative_phrase():
    item = _raw(
        "iPhone 14 128GB",
        "本文情報は薄い IMEI未確認 True Tone未確認",
    )
    norm = RuleBasedExtractor().extract(item)
    assert norm.face_id_flag is None
    assert "description_inconsistency" in norm.risk_flags


def test_notification_text_is_used_as_fallback_signal():
    item = _raw("", "")
    item.notification_text = "iPhone 13 128GB SIMフリー バッテリー85%"

    norm = RuleBasedExtractor().extract(item)

    assert norm.model_name == "iPhone 13"
    assert norm.storage_gb == 128
    assert norm.sim_free_flag is True
    assert norm.battery_health == 85


def test_negative_phrases_do_not_trigger_screen_or_repair_flags():
    item = _raw(
        "iPhone 15 128GB",
        "画面割れなし 修理歴なし バッテリー87% SIMフリー",
    )
    norm = RuleBasedExtractor().extract(item)

    assert norm.screen_issue_flag is False
    assert norm.repair_history_flag is False
    assert "repair_history" not in norm.risk_flags


def test_carrier_and_sim_free_variants_are_normalized():
    item = _raw(
        "iPhone 14 128GB Y!mobile SiMフリー",
        "docomo版も比較済み UQ mobile ではない",
    )
    norm = RuleBasedExtractor().extract(item)
    assert norm.storage_gb == 128
    assert norm.sim_free_flag is True
    assert norm.carrier == "docomo"


def test_storage_invalid_values_are_rejected():
    item = _raw(
        "iPhone13 265GB SiMフリー",
        "Apple iPhone 14128GB ミッドナイト 本体",
    )
    norm = RuleBasedExtractor().extract(item)
    assert norm.storage_gb is None
    assert norm.sim_free_flag is True


def test_storage_slash_format_is_still_extracted():
    item = _raw(
        "iPhone13/256GB/RED by メルカリ",
        "",
    )
    norm = RuleBasedExtractor().extract(item)
    assert norm.model_name == "iPhone 13"
    assert norm.storage_gb == 256


def test_model_extraction_supports_12_and_16_series():
    item_12 = _raw("iPhone12 mini 128GB", "")
    norm_12 = RuleBasedExtractor().extract(item_12)
    assert norm_12.model_name == "iPhone 12 mini"

    item_16 = _raw("iphone16 pro 256GB", "")
    norm_16 = RuleBasedExtractor().extract(item_16)
    assert norm_16.model_name == "iPhone 16 Pro"
