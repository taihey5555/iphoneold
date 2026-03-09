import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.cli.entrypoint import main
from app.models import CandidateItem, NormalizedFields, RawListing
from app.repositories.item_repository import ItemRepository
from app.scoring import ProfitEstimator


def _write_test_config(path: Path, db_path: Path) -> None:
    path.write_text(
        f"""
app:
  timezone: "Asia/Tokyo"
  min_profit_yen: 3000
  max_risk_score: 4
  duplicate_window_minutes: 180
  fetch_timeout_seconds: 20
  request_interval_seconds: 0.1
  use_dynamic_fetch: false
  db_path: "{db_path.as_posix()}"
  max_detail_per_listing_page: 3
  max_notifications_per_run: 3
  notification_mode: "concise"
scoring: {{}}
notification: {{}}
buyback:
  target_profit_yen: 5000
  estimated_shipping_cost_yen: 750
  estimated_fee_yen: 0
  default_haircut_yen: 2000
  grade_pricing_extra_haircut_yen: 1000
  stale_quote_days: 14
targets: []
sources: []
""".strip(),
        encoding="utf-8",
    )


def _insert_item(db_path: Path, source: str, item_url: str) -> None:
    repo = ItemRepository(str(db_path))
    raw = RawListing(
        source=source,
        item_url=item_url,
        title="iPhone 14 128GB",
        description="",
        listed_price=50000,
        shipping_fee=0,
        posted_at=None,
        seller_name="seller",
        image_urls=[],
        fetched_at=datetime.now(timezone.utc),
    )
    item = CandidateItem(raw=raw, normalized=NormalizedFields(model_name="iPhone 14", storage_gb=128), exclude_reason=None)
    repo.upsert_scored_item(ProfitEstimator([]).score(item))


def test_cli_buyback_shop_add_list_and_update(tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    db_path = tmp_path / "test.db"
    _write_test_config(config_path, db_path)

    rc = main(
        [
            "--config",
            str(config_path),
            "--env",
            str(tmp_path / ".env"),
            "buyback-shop",
            "add",
            "--shop-name",
            "UsedA",
            "--accepts-opened-unused",
            "--supports-grade-pricing",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "created:" in out

    rc = main(
        [
            "--config",
            str(config_path),
            "--env",
            str(tmp_path / ".env"),
            "buyback-shop",
            "list",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "UsedA" in out
    assert "opened_unused=yes" in out

    rc = main(
        [
            "--config",
            str(config_path),
            "--env",
            str(tmp_path / ".env"),
            "buyback-shop",
            "update",
            "--shop",
            "1",
            "--inactive",
            "--notes",
            "paused",
        ]
    )
    assert rc == 0
    capsys.readouterr()

    rc = main(
        [
            "--config",
            str(config_path),
            "--env",
            str(tmp_path / ".env"),
            "buyback-shop",
            "list",
            "--format",
            "json",
        ]
    )
    assert rc == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["is_active"] is False
    assert rows[0]["notes"] == "paused"


def test_cli_buyback_quote_and_evaluate_exit(tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    db_path = tmp_path / "test.db"
    _write_test_config(config_path, db_path)
    item_url = "https://jp.mercari.com/item/m123"
    _insert_item(db_path, "mercari_public", item_url)

    assert (
        main(
            [
                "--config",
                str(config_path),
                "--env",
                str(tmp_path / ".env"),
                "review-status",
                "set",
                "--source",
                "mercari_public",
                "--item-url",
                item_url,
                "--status",
                "watched",
                "--item-category",
                "used",
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert (
        main(
            [
                "--config",
                str(config_path),
                "--env",
                str(tmp_path / ".env"),
                "buyback-shop",
                "add",
                "--shop-name",
                "UsedA",
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert (
        main(
            [
                "--config",
                str(config_path),
                "--env",
                str(tmp_path / ".env"),
                "buyback-quote",
                "set",
                "--source",
                "mercari_public",
                "--item-url",
                item_url,
                "--shop",
                "UsedA",
                "--category",
                "used",
                "--min",
                "63000",
                "--max",
                "65000",
                "--condition-assumption",
                "B rank",
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert (
        main(
            [
                "--config",
                str(config_path),
                "--env",
                str(tmp_path / ".env"),
                "buyback-quote",
                "list",
                "--source",
                "mercari_public",
                "--item-url",
                item_url,
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "UsedA" in out
    assert "min=63000" in out

    assert (
        main(
            [
                "--config",
                str(config_path),
                "--env",
                str(tmp_path / ".env"),
                "review-status",
                "evaluate-exit",
                "--source",
                "mercari_public",
                "--item-url",
                item_url,
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "decision: should_buy" in out
    assert "conservative_exit_price: 63000" in out

    assert (
        main(
            [
                "--config",
                str(config_path),
                "--env",
                str(tmp_path / ".env"),
                "review-status",
                "evaluate-exit",
                "--source",
                "mercari_public",
                "--item-url",
                item_url,
                "--format",
                "json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["decision"] == "should_buy"
    assert payload["item_category"] == "used"


def test_existing_outcome_set_with_buyback_shop_still_works(tmp_path):
    config_path = tmp_path / "config.yaml"
    db_path = tmp_path / "test.db"
    _write_test_config(config_path, db_path)
    item_url = "https://jp.mercari.com/item/m999"
    _insert_item(db_path, "mercari_public", item_url)

    assert (
        main(
            [
                "--config",
                str(config_path),
                "--env",
                str(tmp_path / ".env"),
                "review-status",
                "outcome-set",
                "--source",
                "mercari_public",
                "--item-url",
                item_url,
                "--outcome",
                "buyback_done",
                "--exit-channel",
                "buyback_shop",
                "--sale-price",
                "61000",
            ]
        )
        == 0
    )

    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT exit_channel, outcome_status, actual_sale_price FROM items WHERE source = ? AND item_url = ?",
        ("mercari_public", item_url),
    ).fetchone()
    conn.close()
    assert row == ("buyback_shop", "buyback_done", 61000)
