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


def _set_fetched_at(db_path: Path, source: str, item_url: str, fetched_at_iso: str) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "UPDATE items SET fetched_at = ? WHERE source = ? AND item_url = ?",
        (fetched_at_iso, source, item_url),
    )
    conn.commit()
    conn.close()


def test_cli_review_status_set_and_list(tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    db_path = tmp_path / "test.db"
    _write_test_config(config_path, db_path)
    _insert_item(db_path, "mercari_public", "https://jp.mercari.com/item/m123")

    rc = main(
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
            "https://jp.mercari.com/item/m123",
            "--status",
            "good",
            "--note",
            "price is strong",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "updated:" in out

    rc2 = main(
        [
            "--config",
            str(config_path),
            "--env",
            str(tmp_path / ".env"),
            "review-status",
            "list",
            "--limit",
            "10",
            "--status",
            "good",
        ]
    )
    assert rc2 == 0
    out2 = capsys.readouterr().out
    assert "review_status" in out2
    assert "mercari_public" in out2
    assert "good" in out2
    assert "price is strong" in out2


def test_cli_review_status_set_not_found(tmp_path):
    config_path = tmp_path / "config.yaml"
    db_path = tmp_path / "test.db"
    _write_test_config(config_path, db_path)
    rc = main(
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
            "https://jp.mercari.com/item/not-found",
            "--status",
            "bad",
        ]
    )
    assert rc == 1


def test_cli_review_status_list_formats_and_summary(tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    db_path = tmp_path / "test.db"
    _write_test_config(config_path, db_path)
    _insert_item(db_path, "mercari_public", "https://jp.mercari.com/item/m1")
    _insert_item(db_path, "mercari_public", "https://jp.mercari.com/item/m2")
    _insert_item(db_path, "mercari_public", "https://jp.mercari.com/item/m3")

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
                "https://jp.mercari.com/item/m1",
                "--status",
                "good",
            ]
        )
        == 0
    )
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
                "https://jp.mercari.com/item/m2",
                "--status",
                "bad",
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
                "review-status",
                "list",
                "--format",
                "json",
                "--limit",
                "10",
            ]
        )
        == 0
    )
    list_json = capsys.readouterr().out
    assert list_json.strip().startswith("[")
    assert "review_status" in list_json

    assert (
        main(
            [
                "--config",
                str(config_path),
                "--env",
                str(tmp_path / ".env"),
                "review-status",
                "list",
                "--format",
                "csv",
                "--limit",
                "10",
            ]
        )
        == 0
    )
    list_csv = capsys.readouterr().out
    assert "source,review_status,review_note,exit_channel,outcome_status,actual_sale_price,actual_profit,outcome_note,listed_price" in list_csv

    assert (
        main(
            [
                "--config",
                str(config_path),
                "--env",
                str(tmp_path / ".env"),
                "review-status",
                "summary",
                "--format",
                "tsv",
            ]
        )
        == 0
    )
    summary_tsv = capsys.readouterr().out
    assert "total_items\t3" in summary_tsv
    assert "good_count\t1" in summary_tsv
    assert "bad_count\t1" in summary_tsv
    assert "pending_count\t1" in summary_tsv
    assert "average_estimated_profit\t" in summary_tsv

    assert (
        main(
            [
                "--config",
                str(config_path),
                "--env",
                str(tmp_path / ".env"),
                "review-status",
                "summary",
                "--status",
                "good",
                "--format",
                "json",
            ]
        )
        == 0
    )
    summary_json = capsys.readouterr().out
    payload = json.loads(summary_json)
    assert payload["good_count"] == 1
    assert payload["total_items"] == 1
    assert payload["status_average_estimated_profit"]["good"] is not None


def test_cli_review_status_list_missing_item_category_and_exit_eval(tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    db_path = tmp_path / "test.db"
    _write_test_config(config_path, db_path)
    url_missing = "https://jp.mercari.com/item/missing1"
    url_used = "https://jp.mercari.com/item/used1"
    _insert_item(db_path, "mercari_public", url_missing)
    _insert_item(db_path, "mercari_public", url_used)

    repo = ItemRepository(str(db_path))
    assert repo.update_item_category("mercari_public", url_used, "used")
    shop_id = repo.add_buyback_shop("UsedA", accepts_used=True)
    repo.insert_buyback_quote("mercari_public", url_used, shop_id, "used", 63000, 65000, "B")

    assert (
        main(
            [
                "--config",
                str(config_path),
                "--env",
                str(tmp_path / ".env"),
                "review-status",
                "list",
                "--missing-item-category",
                "--format",
                "json",
            ]
        )
        == 0
    )
    missing_rows = json.loads(capsys.readouterr().out)
    assert len(missing_rows) == 1
    assert missing_rows[0]["item_url"] == url_missing
    assert missing_rows[0]["item_category_hint"] is None

    assert (
        main(
            [
                "--config",
                str(config_path),
                "--env",
                str(tmp_path / ".env"),
                "review-status",
                "list",
                "--with-exit-eval",
                "--format",
                "json",
            ]
        )
        == 0
    )
    rows = json.loads(capsys.readouterr().out)
    used_row = next(row for row in rows if row["item_url"] == url_used)
    assert used_row["item_category"] == "used"
    assert used_row["conservative_exit_price"] == 63000
    assert used_row["max_purchase_price"] == 55250
    assert used_row["decision"] == "should_buy"
    assert used_row["stale_quote_found"] is False

    assert (
        main(
            [
                "--config",
                str(config_path),
                "--env",
                str(tmp_path / ".env"),
                "review-status",
                "list",
                "--with-buyback-floor",
                "--format",
                "json",
            ]
        )
        == 0
    )
    floor_rows = json.loads(capsys.readouterr().out)
    used_floor_row = next(row for row in floor_rows if row["item_url"] == url_used)
    assert used_floor_row["buyback_floor"] == 63000
    assert used_floor_row["floor_gap"] == 13000
    assert used_floor_row["buyback_decision"] == "should_buy"
    assert used_floor_row["buyback_stale_quote_found"] is False


def test_cli_review_status_imei_show_and_list_visibility(tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    db_path = tmp_path / "test.db"
    _write_test_config(config_path, db_path)
    repo = ItemRepository(str(db_path))
    raw = RawListing(
        source="mercari_public",
        item_url="https://jp.mercari.com/item/imei1",
        title="iPhone 14 128GB",
        description="IMEI 356789012345678",
        listed_price=50000,
        shipping_fee=0,
        posted_at=None,
        seller_name="seller",
        image_urls=[],
        fetched_at=datetime.now(timezone.utc),
    )
    item = CandidateItem(raw=raw, normalized=NormalizedFields(model_name="iPhone 14", storage_gb=128, imei_candidates=["356789012345678"]), exclude_reason=None)
    repo.upsert_scored_item(ProfitEstimator([]).score(item))

    assert (
        main(
            [
                "--config",
                str(config_path),
                "--env",
                str(tmp_path / ".env"),
                "review-status",
                "imei-show",
                "--source",
                "mercari_public",
                "--item-url",
                "https://jp.mercari.com/item/imei1",
                "--format",
                "json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["imei_candidates"] == ["356789012345678"]
    assert payload["check_url"] == "https://naoseru.com/ja/imei-checker/"

    assert (
        main(
            [
                "--config",
                str(config_path),
                "--env",
                str(tmp_path / ".env"),
                "review-status",
                "list",
                "--format",
                "human",
            ]
        )
        == 0
    )
    human = capsys.readouterr().out
    assert "imei_count=1" in human
    assert "imei=356789012345678 check_url=https://naoseru.com/ja/imei-checker/" in human


def test_cli_review_status_list_notified_only(tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    db_path = tmp_path / "test.db"
    _write_test_config(config_path, db_path)
    url_notified = "https://jp.mercari.com/item/notified1"
    url_plain = "https://jp.mercari.com/item/plain1"
    _insert_item(db_path, "mercari_public", url_notified)
    _insert_item(db_path, "mercari_public", url_plain)
    repo = ItemRepository(str(db_path))
    repo.mark_notified("mercari_public", url_notified)

    assert (
        main(
            [
                "--config",
                str(config_path),
                "--env",
                str(tmp_path / ".env"),
                "review-status",
                "list",
                "--notified-only",
                "--format",
                "json",
            ]
        )
        == 0
    )
    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == 1
    assert rows[0]["item_url"] == url_notified


def test_cli_review_status_item_category_check_and_hint(tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    db_path = tmp_path / "test.db"
    _write_test_config(config_path, db_path)
    repo = ItemRepository(str(db_path))
    raw_missing = RawListing(
        source="mercari_public",
        item_url="https://jp.mercari.com/item/h1",
        title="iPhone 14 128GB",
        description="開封済み未使用 動作確認のみ",
        listed_price=50000,
        shipping_fee=0,
        posted_at=None,
        seller_name="seller",
        image_urls=[],
        fetched_at=datetime.now(timezone.utc),
    )
    raw_used = RawListing(
        source="mercari_public",
        item_url="https://jp.mercari.com/item/h2",
        title="iPhone 14 128GB",
        description="通常中古",
        listed_price=50000,
        shipping_fee=0,
        posted_at=None,
        seller_name="seller",
        image_urls=[],
        fetched_at=datetime.now(timezone.utc),
    )
    item_missing = CandidateItem(raw=raw_missing, normalized=NormalizedFields(model_name="iPhone 14", storage_gb=128), exclude_reason=None)
    item_used = CandidateItem(raw=raw_used, normalized=NormalizedFields(model_name="iPhone 14", storage_gb=128), exclude_reason=None)
    repo.upsert_scored_item(ProfitEstimator([]).score(item_missing))
    repo.upsert_scored_item(ProfitEstimator([]).score(item_used))
    assert repo.update_item_category("mercari_public", "https://jp.mercari.com/item/h2", "used")

    assert (
        main(
            [
                "--config",
                str(config_path),
                "--env",
                str(tmp_path / ".env"),
                "review-status",
                "item-category-check",
                "--format",
                "json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["item_category_column_exists"] is True
    assert payload["items_total"] == 2
    assert payload["item_category_missing_count"] == 1
    assert payload["item_category_filled_count"] == 1
    assert payload["item_category_distribution"]["used"] == 1
    assert payload["item_category_distribution"]["opened_unused"] == 0
    assert payload["item_category_distribution"]["null"] == 1
    assert payload["opened_unused_hint_count"] == 1

    assert (
        main(
            [
                "--config",
                str(config_path),
                "--env",
                str(tmp_path / ".env"),
                "review-status",
                "list",
                "--missing-item-category",
                "--format",
                "json",
            ]
        )
        == 0
    )
    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == 1
    assert rows[0]["item_category_hint"] == "opened_unused"

    assert (
        main(
            [
                "--config",
                str(config_path),
                "--env",
                str(tmp_path / ".env"),
                "review-status",
                "list",
                "--missing-item-category",
                "--format",
                "human",
            ]
        )
        == 0
    )
    human = capsys.readouterr().out
    assert "hint=opened_unused" in human
    assert "url=https://jp.mercari.com/item/h1" in human


def test_item_repository_migrates_item_category_column_for_legacy_db(tmp_path):
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE items (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          source TEXT NOT NULL,
          item_url TEXT NOT NULL,
          title TEXT NOT NULL,
          description TEXT NOT NULL,
          listed_price INTEGER NOT NULL,
          shipping_fee INTEGER NOT NULL,
          posted_at TEXT,
          seller_name TEXT,
          image_urls_json TEXT NOT NULL,
          fetched_at TEXT NOT NULL,
          normalized_json TEXT NOT NULL,
          expected_resale_price INTEGER NOT NULL,
          estimated_profit INTEGER NOT NULL,
          selling_fee INTEGER NOT NULL,
          shipping_cost INTEGER NOT NULL,
          risk_buffer INTEGER NOT NULL,
          risk_score INTEGER NOT NULL,
          risk_flags_json TEXT NOT NULL,
          exclude_reason TEXT,
          UNIQUE(source, item_url)
        )
        """
    )
    conn.commit()
    conn.close()

    repo = ItemRepository(str(db_path))
    state = repo.summarize_item_category_state()
    assert state["item_category_column_exists"] is True


def test_cli_review_status_set_note_persists_in_json(tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    db_path = tmp_path / "test.db"
    _write_test_config(config_path, db_path)
    _insert_item(db_path, "mercari_public", "https://jp.mercari.com/item/n1")

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
                "https://jp.mercari.com/item/n1",
                "--status",
                "watched",
                "--note",
                "IMEI未確認のため保留",
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
                "review-status",
                "list",
                "--format",
                "json",
                "--limit",
                "10",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["review_note"] == "IMEI未確認のため保留"


def test_cli_outcome_set_and_performance_summary(tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    db_path = tmp_path / "test.db"
    _write_test_config(config_path, db_path)
    _insert_item(db_path, "mercari_public", "https://jp.mercari.com/item/p1")
    _insert_item(db_path, "mercari_public", "https://jp.mercari.com/item/p2")

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
                "https://jp.mercari.com/item/p1",
                "--outcome",
                "sold",
                "--exit-channel",
                "mercari_resale",
                "--sale-price",
                "65000",
                "--note",
                "sold in 2 days",
            ]
        )
        == 0
    )
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
                "https://jp.mercari.com/item/p2",
                "--outcome",
                "buyback_done",
                "--exit-channel",
                "buyback_shop",
                "--sale-price",
                "52000",
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
                "review-status",
                "list",
                "--format",
                "json",
                "--limit",
                "10",
            ]
        )
        == 0
    )
    recent = json.loads(capsys.readouterr().out)
    assert {row["outcome_status"] for row in recent} == {"sold", "buyback_done"}

    assert (
        main(
            [
                "--config",
                str(config_path),
                "--env",
                str(tmp_path / ".env"),
                "review-status",
                "performance",
                "--format",
                "json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["total_items"] == 2
    assert payload["realized_count"] == 2
    assert payload["sold_count"] == 1
    assert payload["buyback_done_count"] == 1
    assert "mercari_resale" in payload["channel_breakdown"]
    assert "buyback_shop" in payload["channel_breakdown"]


def test_cli_daily_notes_sync_updates_target_day_from_review_and_outcome_notes(tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    db_path = tmp_path / "test.db"
    notes_path = tmp_path / "daily_notes.md"
    _write_test_config(config_path, db_path)
    _insert_item(db_path, "mercari_public", "https://jp.mercari.com/item/d1")
    _insert_item(db_path, "mercari_public", "https://jp.mercari.com/item/d2")

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
            "https://jp.mercari.com/item/d1",
            "--status",
            "good",
            "--note",
            "IMEI確認済みで価格が強い",
        ]
    )
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
            "https://jp.mercari.com/item/d2",
            "--status",
            "watched",
            "--note",
            "バッテリー弱めのため保留",
        ]
    )
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
            "https://jp.mercari.com/item/d1",
            "--outcome",
            "sold",
            "--exit-channel",
            "mercari_resale",
            "--sale-price",
            "65000",
            "--note",
            "即売れ",
        ]
    )
    capsys.readouterr()

    repo = ItemRepository(str(db_path))
    repo.mark_notified(
        "mercari_public",
        "https://jp.mercari.com/item/d1",
        notification_reason="notified_reason(profit_current=10000,profit_threshold=3000, risk_current=0,risk_threshold=4, target=iPhone 14 128GB, priority_score=10000)",
    )
    repo.mark_notified(
        "mercari_public",
        "https://jp.mercari.com/item/d2",
        notification_reason="notified_reason(profit_current=6000,profit_threshold=3000, risk_current=2,risk_threshold=4, target=iPhone 14 128GB, priority_score=4800)",
    )

    notes_path.write_text(
        "# log\n\n## Day5（      /      ）\n- [ ] 朝の実行を確認\n- [ ] 昼の実行を確認\n- [ ] 夜の実行を確認\n- [ ] 通知件数を記録（通知なしでも記録）\n- [ ] review_status を更新\n\n### 通知記録\n- 件数:\n- 案件:\n  - なし\n\n### review_status 記録\n- good:\n  - なし\n\n- bad:\n  - なし\n\n- watched:\n  - なし\n\n- bought:\n  - なし\n\n### 気づきメモ\n- なし\n",
        encoding="utf-8",
    )

    assert (
        main(
            [
                "--config",
                str(config_path),
                "--env",
                str(tmp_path / ".env"),
                "review-status",
                "daily-notes-sync",
                "--date",
                "2026-03-09",
                "--day",
                "5",
                "--notes-file",
                str(notes_path),
            ]
        )
        == 0
    )
    content = notes_path.read_text(encoding="utf-8")
    assert "## Day5（2026-03-09）" in content
    assert "- 件数: 2" in content
    assert "https://jp.mercari.com/item/d1" in content
    assert "https://jp.mercari.com/item/d2" in content
    assert "d1" in content
    assert "判定理由: IMEI確認済みで価格が強い" in content
    assert "判定理由: バッテリー弱めのため保留" in content
    assert "sold / mercari_resale / 実粗利" in content


def test_cli_review_status_output_file(tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    db_path = tmp_path / "test.db"
    _write_test_config(config_path, db_path)
    _insert_item(db_path, "mercari_public", "https://jp.mercari.com/item/m10")

    out_path = tmp_path / "out" / "recent.json"
    assert (
        main(
            [
                "--config",
                str(config_path),
                "--env",
                str(tmp_path / ".env"),
                "review-status",
                "list",
                "--format",
                "json",
                "--output",
                str(out_path),
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "written:" in out
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert data[0]["source"] == "mercari_public"

    summary_path = tmp_path / "out" / "summary.tsv"
    assert (
        main(
            [
                "--config",
                str(config_path),
                "--env",
                str(tmp_path / ".env"),
                "review-status",
                "summary",
                "--format",
                "tsv",
                "--output",
                str(summary_path),
            ]
        )
        == 0
    )
    summary_text = summary_path.read_text(encoding="utf-8")
    assert "total_items\t1" in summary_text


def test_cli_review_status_summary_source_breakdown_and_candidate_rates(tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    db_path = tmp_path / "test.db"
    _write_test_config(config_path, db_path)
    _insert_item(db_path, "mercari_public", "https://jp.mercari.com/item/a1")
    _insert_item(db_path, "mercari_public", "https://jp.mercari.com/item/a2")
    _insert_item(db_path, "other_source", "https://example.com/item/b1")
    _insert_item(db_path, "other_source", "https://example.com/item/b2")
    _set_fetched_at(db_path, "mercari_public", "https://jp.mercari.com/item/a1", "2026-03-01T10:00:00+00:00")
    _set_fetched_at(db_path, "mercari_public", "https://jp.mercari.com/item/a2", "2026-03-02T10:00:00+00:00")
    _set_fetched_at(db_path, "other_source", "https://example.com/item/b1", "2026-03-09T10:00:00+00:00")
    _set_fetched_at(db_path, "other_source", "https://example.com/item/b2", "2026-03-10T10:00:00+00:00")

    for args in (
        ["--source", "mercari_public", "--item-url", "https://jp.mercari.com/item/a1", "--status", "good"],
        ["--source", "mercari_public", "--item-url", "https://jp.mercari.com/item/a2", "--status", "bad"],
        ["--source", "other_source", "--item-url", "https://example.com/item/b1", "--status", "bought"],
    ):
        assert (
            main(
                [
                    "--config",
                    str(config_path),
                    "--env",
                    str(tmp_path / ".env"),
                    "review-status",
                    "set",
                    *args,
                ]
            )
            == 0
        )
    capsys.readouterr()

    repo = ItemRepository(str(db_path))
    repo.mark_notified("mercari_public", "https://jp.mercari.com/item/a1")
    repo.mark_notified("mercari_public", "https://jp.mercari.com/item/a2")
    repo.mark_notified("other_source", "https://example.com/item/b1")

    assert (
        main(
            [
                "--config",
                str(config_path),
                "--env",
                str(tmp_path / ".env"),
                "review-status",
                "summary",
                "--format",
                "json",
                "--timeseries",
                "both",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["total_items"] == 4
    assert payload["good_count"] == 1
    assert payload["bad_count"] == 1
    assert payload["bought_count"] == 1
    assert "mercari_public" in payload["source_breakdown"]
    assert "other_source" in payload["source_breakdown"]
    assert payload["source_breakdown"]["mercari_public"]["good_count"] == 1
    assert payload["source_breakdown"]["other_source"]["bought_count"] == 1
    assert payload["candidate_total_items"] == 3
    assert payload["candidate_good_rate"] > 0
    assert payload["candidate_bad_rate"] > 0
    assert payload["candidate_bought_rate"] > 0
    assert len(payload["timeseries_daily"]) >= 2
    assert len(payload["timeseries_weekly"]) >= 2
    assert "mercari_public" in payload["source_timeseries_daily"]
    assert "other_source" in payload["source_timeseries_weekly"]


def test_cli_review_status_summary_timeseries_tsv_csv(tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    db_path = tmp_path / "test.db"
    _write_test_config(config_path, db_path)
    _insert_item(db_path, "mercari_public", "https://jp.mercari.com/item/t1")
    _set_fetched_at(db_path, "mercari_public", "https://jp.mercari.com/item/t1", "2026-03-01T00:00:00+00:00")

    assert (
        main(
            [
                "--config",
                str(config_path),
                "--env",
                str(tmp_path / ".env"),
                "review-status",
                "summary",
                "--format",
                "tsv",
                "--timeseries",
                "daily",
            ]
        )
        == 0
    )
    tsv = capsys.readouterr().out
    assert "daily_bucket" in tsv

    assert (
        main(
            [
                "--config",
                str(config_path),
                "--env",
                str(tmp_path / ".env"),
                "review-status",
                "summary",
                "--format",
                "csv",
                "--timeseries",
                "weekly",
            ]
        )
        == 0
    )
    csv_out = capsys.readouterr().out
    assert "weekly_bucket,total_items" in csv_out
