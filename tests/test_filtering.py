from datetime import datetime, timezone

from app.config import TargetConfig
from app.models import NormalizedFields, RawListing, SourceItem
from app.services.filtering import ExclusionService


def _raw(title: str, desc: str) -> RawListing:
    return RawListing(
        source="x",
        item_url="https://example.com/item/1",
        title=title,
        description=desc,
        listed_price=50000,
        shipping_fee=0,
        posted_at=None,
        seller_name=None,
        image_urls=[],
        fetched_at=datetime.now(timezone.utc),
    )


def test_excludes_box_only():
    svc = ExclusionService([TargetConfig(model="iPhone 14", storage_gb=128, keywords=[], expected_resale_base=70000)])
    norm = NormalizedFields(model_name="iPhone 14", storage_gb=128)
    item = SourceItem(raw=_raw("iPhone 14 空箱", "箱のみ"), normalized=norm)
    out = svc.apply(item)
    assert out.exclude_reason == "box_only"


def test_excludes_out_of_target():
    svc = ExclusionService([TargetConfig(model="iPhone 14", storage_gb=128, keywords=[], expected_resale_base=70000)])
    norm = NormalizedFields(model_name="iPhone 14", storage_gb=256)
    item = SourceItem(raw=_raw("iPhone 14 256GB", "通常品"), normalized=norm)
    out = svc.apply(item)
    assert out.exclude_reason == "out_of_target"


def test_excludes_network_risk():
    svc = ExclusionService([TargetConfig(model="iPhone 14", storage_gb=128, keywords=[], expected_resale_base=70000)])
    norm = NormalizedFields(model_name="iPhone 14", storage_gb=128)
    item = SourceItem(raw=_raw("iPhone 14 128GB", "残債あり"), normalized=norm)
    out = svc.apply(item)
    assert out.exclude_reason == "network_restriction_risk"


def test_does_not_exclude_when_only_accessories_are_box_only():
    svc = ExclusionService([TargetConfig(model="iPhone 13", storage_gb=128, keywords=[], expected_resale_base=63000)])
    norm = NormalizedFields(model_name="iPhone 13", storage_gb=128)
    item = SourceItem(
        raw=_raw("iPhone 13 128GB", "iPhone 13 128GB。付属品は箱のみです。ケーブルはありません。バッテリー87%"),
        normalized=norm,
    )
    out = svc.apply(item)
    assert out.exclude_reason is None
