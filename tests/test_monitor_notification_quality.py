import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from app.config import AppConfig, NotificationConfig, ScoringConfig, Settings, TargetConfig
from app.models import NormalizedFields, RawListing, ScoredItem
from app.repositories.item_repository import ItemRepository
from app.services.monitor import MonitorService, RunStats


class DummyFetcher:
    def fetch(self, url: str, dynamic: bool = False):
        raise NotImplementedError


class DummyExtractor:
    def extract(self, item):
        raise NotImplementedError


class CaptureNotifier:
    def __init__(self) -> None:
        self.sent: list[tuple[ScoredItem, str]] = []

    def send_item(self, item: ScoredItem, reason_summary: str) -> None:
        self.sent.append((item, reason_summary))


def _settings(tmp_path: Path, max_notifications: int = 2) -> Settings:
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
            max_notifications_per_run=max_notifications,
        ),
        scoring=ScoringConfig(),
        targets=[TargetConfig(model="iPhone 14", storage_gb=128, keywords=[], expected_resale_base=76000)],
        sources=[],
        notification=NotificationConfig(
            risk_priority_weights={"battery_service": -4000, "network_restriction_unknown": -1200},
            never_notify_flags=["activation_lock_risk"],
            network_unknown_only_extra_profit=2500,
            network_unknown_only_max_risk_score=2,
        ),
    )


def _load_fixture_items() -> list[ScoredItem]:
    p = Path(__file__).parent / "fixtures" / "realistic_scored_items.json"
    rows = json.loads(p.read_text(encoding="utf-8"))
    out: list[ScoredItem] = []
    for row in rows:
        out.append(
            ScoredItem(
                raw=RawListing(
                    source=row["source"],
                    item_url=row["item_url"],
                    title=row["title"],
                    description=row["description"],
                    listed_price=row["listed_price"],
                    shipping_fee=row["shipping_fee"],
                    posted_at=None,
                    seller_name=row["seller_name"],
                    image_urls=[],
                    fetched_at=datetime.now(timezone.utc),
                ),
                normalized=NormalizedFields(
                    model_name=row["model_name"],
                    storage_gb=row["storage_gb"],
                    risk_flags=row["risk_flags"],
                    risk_score_breakdown=row["risk_score_breakdown"],
                    risk_score=row["risk_score"],
                ),
                expected_resale_price=row["expected_resale_price"],
                estimated_profit=row["estimated_profit"],
                purchase_price=row["purchase_price"],
                selling_fee=row["selling_fee"],
                shipping_cost=row["shipping_cost"],
                risk_buffer=row["risk_buffer"],
                resale_price_reasons=row["resale_price_reasons"],
            )
        )
    return out


def test_send_notifications_sorted_and_limited(tmp_path):
    notifier = CaptureNotifier()
    repo = ItemRepository(str(tmp_path / "test.db"))
    svc = MonitorService(_settings(tmp_path, max_notifications=2), DummyFetcher(), DummyExtractor(), repo, notifier)  # type: ignore[arg-type]
    stats = RunStats()
    candidates = _load_fixture_items()
    svc._send_notifications(candidates, stats)
    assert stats.notified == 2
    # profit high -> low
    assert notifier.sent[0][0].estimated_profit >= notifier.sent[1][0].estimated_profit
    assert "粗利式=" in notifier.sent[0][1]
    assert "risk=" in notifier.sent[0][1]


def test_similarity_suppression_in_same_run(tmp_path):
    notifier = CaptureNotifier()
    repo = ItemRepository(str(tmp_path / "test.db"))
    svc = MonitorService(_settings(tmp_path, max_notifications=3), DummyFetcher(), DummyExtractor(), repo, notifier)  # type: ignore[arg-type]
    stats = RunStats()
    base = _load_fixture_items()[0]
    similar = replace(base, raw=replace(base.raw, item_url="https://jp.mercari.com/item/m99999999999", listed_price=59100))
    svc._send_notifications([base, similar], stats)
    assert stats.notified == 1


def test_priority_rule_changes_order(tmp_path):
    notifier = CaptureNotifier()
    repo = ItemRepository(str(tmp_path / "test.db"))
    svc = MonitorService(_settings(tmp_path, max_notifications=2), DummyFetcher(), DummyExtractor(), repo, notifier)  # type: ignore[arg-type]
    stats = RunStats()
    a, b = _load_fixture_items()[0], _load_fixture_items()[1]
    # b has larger profit but heavy penalty via battery_service => a should rank first
    svc._send_notifications([a, b], stats)
    assert stats.notified == 2
    assert notifier.sent[0][0].raw.item_url == a.raw.item_url


def test_network_unknown_only_is_stricter(tmp_path):
    notifier = CaptureNotifier()
    repo = ItemRepository(str(tmp_path / "test.db"))
    svc = MonitorService(_settings(tmp_path, max_notifications=2), DummyFetcher(), DummyExtractor(), repo, notifier)  # type: ignore[arg-type]
    item = _load_fixture_items()[0]
    item.normalized.risk_flags = ["network_restriction_unknown"]
    item.normalized.risk_score_breakdown = {"network_restriction_unknown": 2}
    item.normalized.risk_score = 2
    item.estimated_profit = 5000  # global min 3000 is OK but stricter rule requires 5500
    ok, reason = svc._should_notify(item)
    assert ok is False
    assert "network_unknown_strict_rule" in reason


def test_reason_codes_profit_risk_never_duplicate(tmp_path):
    notifier = CaptureNotifier()
    repo = ItemRepository(str(tmp_path / "test.db"))
    svc = MonitorService(_settings(tmp_path, max_notifications=2), DummyFetcher(), DummyExtractor(), repo, notifier)  # type: ignore[arg-type]
    item = _load_fixture_items()[0]

    item.estimated_profit = 1000
    ok, reason = svc._should_notify(item)
    assert ok is False
    assert reason.startswith("profit_below_threshold(")

    item.estimated_profit = 7000
    item.normalized.risk_score = 8
    ok, reason = svc._should_notify(item)
    assert ok is False
    assert reason.startswith("risk_too_high(")

    item.normalized.risk_score = 1
    item.normalized.risk_flags = ["activation_lock_risk"]
    ok, reason = svc._should_notify(item)
    assert ok is False
    assert reason.startswith("never_notify_flag(")

    item.normalized.risk_flags = []
    item.normalized.risk_score = 1
    dedupe_key = svc._dedupe_key(item)
    sim_key = svc._similarity_key(item)
    repo.mark_notified(item.raw.source, item.raw.item_url, dedupe_key=dedupe_key, similarity_key=sim_key)
    ok, reason = svc._should_notify(item)
    assert ok is False
    assert reason.startswith("recent_duplicate(")


def test_rejection_codes_max_notifications_and_not_target(tmp_path, caplog):
    notifier = CaptureNotifier()
    repo = ItemRepository(str(tmp_path / "test.db"))
    svc = MonitorService(_settings(tmp_path, max_notifications=1), DummyFetcher(), DummyExtractor(), repo, notifier)  # type: ignore[arg-type]
    stats = RunStats()
    a, b = _load_fixture_items()[0], _load_fixture_items()[2]
    with caplog.at_level("DEBUG"):
        svc._send_notifications([a, b], stats)
    assert stats.notified == 1
    assert any("max_notifications_per_run(" in rec.message for rec in caplog.records)
    assert MonitorService._exclude_reason_code("out_of_target") == "not_target_model"


def test_notified_reason_logged(tmp_path, caplog):
    notifier = CaptureNotifier()
    repo = ItemRepository(str(tmp_path / "test.db"))
    svc = MonitorService(_settings(tmp_path, max_notifications=2), DummyFetcher(), DummyExtractor(), repo, notifier)  # type: ignore[arg-type]
    stats = RunStats()
    item = _load_fixture_items()[0]
    with caplog.at_level("DEBUG"):
        svc._send_notifications([item], stats)
    assert stats.notified == 1
    assert any("candidate notified:" in rec.message and "notified_reason=" in rec.message for rec in caplog.records)
