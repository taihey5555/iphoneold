from datetime import datetime, timezone

from app.config import ScoringConfig, TargetConfig
from app.models import CandidateItem, NormalizedFields, RawListing
from app.scoring import ProfitEstimator


def test_profit_formula():
    estimator = ProfitEstimator([TargetConfig(model="iPhone 13", storage_gb=128, keywords=[], expected_resale_base=63000)])
    raw = RawListing(
        source="x",
        item_url="u",
        title="iPhone 13 128GB",
        description="",
        listed_price=45000,
        shipping_fee=1000,
        posted_at=None,
        seller_name=None,
        image_urls=[],
        fetched_at=datetime.now(timezone.utc),
    )
    norm = NormalizedFields(model_name="iPhone 13", storage_gb=128, sim_free_flag=True, battery_health=90)
    item = CandidateItem(raw=raw, normalized=norm, exclude_reason=None)
    scored = estimator.score(item)
    assert scored.expected_resale_price > 63000
    assert isinstance(scored.estimated_profit, int)


def test_expected_resale_price_uses_config_adjustments():
    estimator = ProfitEstimator(
        [TargetConfig(model="iPhone 13", storage_gb=128, keywords=[], expected_resale_base=63000)],
        ScoringConfig(
            sim_free_bonus=2000,
            battery_bonus_95=2000,
            carrier_penalty=2000,
            carrier_penalties={"docomo": 2000},
        ),
    )
    raw = RawListing(
        source="x",
        item_url="u",
        title="iPhone 13 128GB",
        description="",
        listed_price=45000,
        shipping_fee=1000,
        posted_at=None,
        seller_name=None,
        image_urls=[],
        fetched_at=datetime.now(timezone.utc),
    )
    norm = NormalizedFields(model_name="iPhone 13", storage_gb=128, sim_free_flag=True, battery_health=95, carrier="docomo")
    item = CandidateItem(raw=raw, normalized=norm, exclude_reason=None)
    scored = estimator.score(item)
    # 63000 +2000(sim_free) -2000(carrier) +2000(battery>=95) = 65000
    assert scored.expected_resale_price == 65000


def test_expected_resale_price_applies_unknown_penalties():
    estimator = ProfitEstimator(
        [TargetConfig(model="iPhone 14", storage_gb=128, keywords=[], expected_resale_base=76000)],
        ScoringConfig(sim_unknown_penalty=1000, unknown_carrier_penalty=500),
    )
    raw = RawListing(
        source="x",
        item_url="u2",
        title="iPhone 14 128GB",
        description="",
        listed_price=60000,
        shipping_fee=0,
        posted_at=None,
        seller_name=None,
        image_urls=[],
        fetched_at=datetime.now(timezone.utc),
    )
    norm = NormalizedFields(model_name="iPhone 14", storage_gb=128, sim_free_flag=None, battery_health=88, carrier=None)
    item = CandidateItem(raw=raw, normalized=norm, exclude_reason=None)
    scored = estimator.score(item)
    # 76000 -1000(sim unknown) -500(carrier unknown) +500(battery>=85) = 75000
    assert scored.expected_resale_price == 75000
