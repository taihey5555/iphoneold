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
    assert "source,review_status,listed_price" in list_csv

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
