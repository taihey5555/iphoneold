import json
import sqlite3
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
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


def _insert_item(
    db_path: Path,
    source: str,
    item_url: str,
    *,
    title: str = "iPhone 14 128GB",
    model_name: str = "iPhone 14",
    storage_gb: int = 128,
    carrier: str | None = None,
    sim_free_flag: bool | None = None,
    item_category: str | None = None,
) -> None:
    repo = ItemRepository(str(db_path))
    raw = RawListing(
        source=source,
        item_url=item_url,
        title=title,
        description="",
        listed_price=50000,
        shipping_fee=0,
        posted_at=None,
        seller_name="seller",
        image_urls=[],
        fetched_at=datetime.now(timezone.utc),
    )
    item = CandidateItem(
        raw=raw,
        normalized=NormalizedFields(
            model_name=model_name,
            storage_gb=storage_gb,
            carrier=carrier,
            sim_free_flag=sim_free_flag,
        ),
        exclude_reason=None,
    )
    repo.upsert_scored_item(ProfitEstimator([]).score(item))
    if item_category:
        repo.update_item_category(source, item_url, item_category)


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


def test_cli_evaluate_exit_can_save_note_and_compare_actual(tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    db_path = tmp_path / "test.db"
    _write_test_config(config_path, db_path)
    item_url = "https://jp.mercari.com/item/m-note"
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
                "--note",
                "manual note",
                "--item-category",
                "used",
            ]
        )
        == 0
    )
    capsys.readouterr()

    repo = ItemRepository(str(db_path))
    shop_id = repo.add_buyback_shop("UsedA", accepts_used=True)
    repo.insert_buyback_quote("mercari_public", item_url, shop_id, "used", 63000, 65000, "B")

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
                "61500",
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
                "evaluate-exit",
                "--source",
                "mercari_public",
                "--item-url",
                item_url,
                "--save-note",
                "--format",
                "json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["actual_sale_price"] == 61500
    assert payload["actual_vs_conservative_exit_price"] == -1500
    assert payload["actual_vs_max_purchase_price"] == 6250

    conn = sqlite3.connect(str(db_path))
    note = conn.execute(
        "SELECT review_note FROM items WHERE source = ? AND item_url = ?",
        ("mercari_public", item_url),
    ).fetchone()[0]
    conn.close()
    assert "manual note" in note
    assert "[exit-eval]" in note


def test_cli_buyback_config_show(tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    db_path = tmp_path / "test.db"
    _write_test_config(config_path, db_path)

    assert (
        main(
            [
                "--config",
                str(config_path),
                "--env",
                str(tmp_path / ".env"),
                "buyback",
                "config",
                "show",
                "--format",
                "json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["stale_quote_days"] == 14
    assert payload["target_profit_yen"] == 5000
    assert payload["grade_pricing_extra_haircut_yen"] == 1000


def test_cli_buyback_quote_list_marks_stale_quotes(tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    db_path = tmp_path / "test.db"
    _write_test_config(config_path, db_path)
    item_url = "https://jp.mercari.com/item/m-stale"
    _insert_item(db_path, "mercari_public", item_url)

    repo = ItemRepository(str(db_path))
    shop_id = repo.add_buyback_shop("UsedA", accepts_used=True)
    stale_at = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    repo.insert_buyback_quote("mercari_public", item_url, shop_id, "used", 62000, quote_checked_at=stale_at)

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
    assert "stale=yes" in out
    assert "age_days=" in out


def test_cli_buyback_quote_import_tsv(tmp_path, capsys):
    config_path = tmp_path / "config.yaml"
    db_path = tmp_path / "test.db"
    _write_test_config(config_path, db_path)
    item_url_1 = "https://jp.mercari.com/item/import1"
    item_url_2 = "https://jp.mercari.com/item/import2"
    _insert_item(db_path, "mercari_public", item_url_1)
    _insert_item(db_path, "mercari_public", item_url_2)

    repo = ItemRepository(str(db_path))
    repo.add_buyback_shop("UsedA", accepts_used=True)
    repo.add_buyback_shop("UsedB", accepts_opened_unused=True)

    input_path = tmp_path / "quotes.tsv"
    input_path.write_text(
        "\n".join(
            [
                "source\titem_url\tshop\tcategory\tmin\tmax\tcondition_assumption\tquote_checked_at",
                f"mercari_public\t{item_url_1}\tUsedA\tused\t61000\t64000\tB\t2026-03-01T00:00:00+00:00",
                f"mercari_public\t{item_url_2}\tUsedB\topened_unused\t70000\t72000\tunused-opened\t2026-03-02T00:00:00+00:00",
            ]
        ),
        encoding="utf-8",
    )

    assert (
        main(
            [
                "--config",
                str(config_path),
                "--env",
                str(tmp_path / ".env"),
                "buyback-quote",
                "import",
                "--input",
                str(input_path),
                "--format",
                "tsv",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "imported: 2" in out

    rows_1 = repo.list_buyback_quotes("mercari_public", item_url_1)
    rows_2 = repo.list_buyback_quotes("mercari_public", item_url_2)
    assert rows_1[0]["quoted_price_min"] == 61000
    assert rows_2[0]["item_category"] == "opened_unused"


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


def test_cli_buyback_quote_fetch_iosys_saves_summary_and_skips_duplicates(tmp_path, capsys, monkeypatch):
    config_path = tmp_path / "config.yaml"
    db_path = tmp_path / "test.db"
    _write_test_config(config_path, db_path)
    item_url_1 = "https://jp.mercari.com/item/iosys-used"
    item_url_2 = "https://jp.mercari.com/item/iosys-opened"
    _insert_item(
        db_path,
        "mercari_public",
        item_url_1,
        title="Apple iPhone 14 Pro 128GB",
        model_name="iPhone 14 Pro",
        storage_gb=128,
        carrier="docomo",
        item_category="used",
    )
    _insert_item(
        db_path,
        "mercari_public",
        item_url_2,
        title="iPhone 14 Pro 128GB",
        model_name="iPhone 14 Pro",
        storage_gb=128,
        carrier="docomo",
        item_category="opened_unused",
    )

    html = """
    <table>
      <tr>
        <th>機種</th>
        <th>容量</th>
        <th>キャリア</th>
        <th>未使用</th>
        <th>中古</th>
      </tr>
      <tr>
        <td>Apple iPhone 14 Pro （SIM）</td>
        <td>128GB</td>
        <td>docomo</td>
        <td>70,000円</td>
        <td>60,000〜65,000円</td>
      </tr>
      <tr>
        <td>iPhone 15</td>
        <td>256GB</td>
        <td>SIMフリー</td>
        <td>80,000円</td>
        <td>72,000円</td>
      </tr>
    </table>
    """

    def fake_fetch(self, url: str, dynamic: bool = False):
        return SimpleNamespace(url=url, html=html)

    monkeypatch.setattr("app.cli.entrypoint.ScraplingFetcher.fetch", fake_fetch)

    rc = main(
        [
            "--config",
            str(config_path),
            "--env",
            str(tmp_path / ".env"),
            "buyback-quote",
            "fetch-iosys",
            "--source-url",
            "https://iosys.example/buyback/iphone",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "saved=2" in out
    assert "skipped=0" in out
    assert "unmatched_quote_rows=2" in out
    assert "expanded_item_count=2" in out
    assert "unmatched_reasons:" in out
    assert "model=iPhone 15 carrier=sim_free storage=256" in out

    rc = main(
        [
            "--config",
            str(config_path),
            "--env",
            str(tmp_path / ".env"),
            "buyback-quote",
            "fetch-iosys",
            "--source-url",
            "https://iosys.example/buyback/iphone",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "saved=0" in out
    assert "skipped=2" in out
    assert "unmatched_quote_rows=2" in out
    assert "expanded_item_count=2" in out

    repo = ItemRepository(str(db_path))
    used_rows = repo.list_buyback_quotes("mercari_public", item_url_1)
    opened_rows = repo.list_buyback_quotes("mercari_public", item_url_2)
    assert len(used_rows) == 1
    assert len(opened_rows) == 1
    assert used_rows[0]["quoted_price_min"] == 60000
    assert used_rows[0]["quoted_price_max"] == 65000
    assert opened_rows[0]["item_category"] == "opened_unused"
    assert opened_rows[0]["notes"] == "iosys:auto:model=Apple iPhone 14 Pro （SIM）;carrier=docomo;storage=128"


def test_cli_buyback_quote_fetch_iosys_json_reports_unmatched_reasons(tmp_path, capsys, monkeypatch):
    config_path = tmp_path / "config.yaml"
    db_path = tmp_path / "test.db"
    _write_test_config(config_path, db_path)
    _insert_item(
        db_path,
        "mercari_public",
        "https://jp.mercari.com/item/iosys-missing-category",
        model_name="iPhone 14 Pro",
        storage_gb=128,
        carrier="docomo",
        item_category=None,
    )
    _insert_item(
        db_path,
        "mercari_public",
        "https://jp.mercari.com/item/iosys-wrong-category",
        model_name="iPhone 14 Pro",
        storage_gb=128,
        carrier="docomo",
        item_category="opened_unused",
    )
    _insert_item(
        db_path,
        "mercari_public",
        "https://jp.mercari.com/item/iosys-storage-only",
        model_name="iPhone 15 Pro",
        storage_gb=256,
        carrier="docomo",
        item_category="used",
    )

    html = """
    <table>
      <tr>
        <th>機種</th>
        <th>容量</th>
        <th>キャリア</th>
        <th>未使用</th>
        <th>中古</th>
      </tr>
      <tr>
        <td>Apple iPhone 14 Pro</td>
        <td>128GB</td>
        <td>docomo</td>
        <td>-</td>
        <td>60,000円</td>
      </tr>
      <tr>
        <td>Apple iPhone 15</td>
        <td>256GB</td>
        <td>SIMフリー</td>
        <td>-</td>
        <td>70,000円</td>
      </tr>
    </table>
    """

    def fake_fetch(self, url: str, dynamic: bool = False):
        return SimpleNamespace(url=url, html=html)

    monkeypatch.setattr("app.cli.entrypoint.ScraplingFetcher.fetch", fake_fetch)

    rc = main(
        [
            "--config",
            str(config_path),
            "--env",
            str(tmp_path / ".env"),
            "buyback-quote",
            "fetch-iosys",
            "--source-url",
            "https://iosys.example/buyback/iphone",
            "--format",
            "json",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["saved_count"] == 0
    assert payload["unmatched_quote_rows"] == 2
    assert payload["item_category_missing_count"] == 1
    assert payload["unmatched_reason_counts"]["item_category_missing"] == 1
    assert payload["unmatched_reason_counts"]["no_candidate_by_carrier"] == 1
    assert payload["unmatched_examples"][0]["model_name_raw"] == "Apple iPhone 14 Pro"
