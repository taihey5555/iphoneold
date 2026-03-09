from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
from io import StringIO
from pathlib import Path
from typing import Sequence

from app.config import Settings
from app.extractors.rule_based import RuleBasedExtractor
from app.models import BUYBACK_ITEM_CATEGORIES
from app.notifiers import TelegramNotifier
from app.repositories import ItemRepository, ScraplingFetcher
from app.services import BuybackEvaluationService, IosysBuybackService, MonitorService
from app.services.buyback import compute_quote_age_days, is_quote_stale
from app.ui import run_review_ui

REVIEW_STATUSES = ("pending", "watched", "good", "bad", "bought")
EXIT_CHANNELS = ("mercari_resale", "buyback_shop")
OUTCOME_STATUSES = ("none", "passed", "bought", "sold", "buyback_done", "loss")


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Used smartphone monitor bot")
    parser.add_argument("--config", default="config.yaml", help="config yaml path")
    parser.add_argument("--env", default=".env", help=".env path")
    parser.add_argument("--verbose", action="store_true", help="enable debug logs")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("run-once", help="Run one monitoring cycle")

    review = sub.add_parser("review-status", help="Review status operations")
    review_sub = review.add_subparsers(dest="review_command", required=True)

    set_cmd = review_sub.add_parser("set", help="Update review_status for an item")
    set_cmd.add_argument("--source", required=True, help="item source")
    set_cmd.add_argument("--item-url", required=True, help="item url")
    set_cmd.add_argument("--status", required=True, choices=REVIEW_STATUSES, help="new review status")
    set_cmd.add_argument("--note", default=None, help="optional review note")
    set_cmd.add_argument("--item-category", default=None, choices=BUYBACK_ITEM_CATEGORIES, help="optional item category")

    outcome_cmd = review_sub.add_parser("outcome-set", help="Update actual outcome for an item")
    outcome_cmd.add_argument("--source", required=True, help="item source")
    outcome_cmd.add_argument("--item-url", required=True, help="item url")
    outcome_cmd.add_argument("--outcome", required=True, choices=OUTCOME_STATUSES, help="actual outcome status")
    outcome_cmd.add_argument("--exit-channel", default=None, choices=EXIT_CHANNELS, help="exit channel for realized trade")
    outcome_cmd.add_argument("--sale-price", type=int, default=None, help="actual sale or buyback price")
    outcome_cmd.add_argument("--note", default=None, help="optional outcome note")

    list_cmd = review_sub.add_parser("list", help="List recent items with review_status")
    list_cmd.add_argument("--limit", type=int, default=20, help="number of rows")
    list_cmd.add_argument("--source", default=None, help="filter by source")
    list_cmd.add_argument("--status", default=None, choices=REVIEW_STATUSES, help="filter by review status")
    list_cmd.add_argument("--missing-item-category", action="store_true", help="show only items missing item_category")
    list_cmd.add_argument("--notified-only", action="store_true", help="show only notified items")
    list_cmd.add_argument("--with-exit-eval", action="store_true", help="include exit evaluation helper columns")
    list_cmd.add_argument("--with-buyback-floor", action="store_true", help="include conservative buyback floor helper columns")
    list_cmd.add_argument("--format", default="tsv", choices=("human", "tsv", "csv", "json"), help="output format")
    list_cmd.add_argument("--output", default=None, help="write output to file")

    summary_cmd = review_sub.add_parser("summary", help="Summary metrics by review_status")
    summary_cmd.add_argument("--source", default=None, help="filter by source")
    summary_cmd.add_argument("--status", default=None, choices=REVIEW_STATUSES, help="filter by review status")
    summary_cmd.add_argument("--timeseries", default="both", choices=("none", "daily", "weekly", "both"), help="timeseries interval")
    summary_cmd.add_argument("--format", default="tsv", choices=("tsv", "csv", "json"), help="output format")
    summary_cmd.add_argument("--output", default=None, help="write output to file")

    performance_cmd = review_sub.add_parser("performance", help="Summary metrics by actual outcomes")
    performance_cmd.add_argument("--source", default=None, help="filter by source")
    performance_cmd.add_argument("--exit-channel", default=None, choices=EXIT_CHANNELS, help="filter by exit channel")
    performance_cmd.add_argument("--format", default="tsv", choices=("tsv", "csv", "json"), help="output format")
    performance_cmd.add_argument("--output", default=None, help="write output to file")

    notes_cmd = review_sub.add_parser("daily-notes-sync", help="Sync a Day section in daily_notes.md from review notes and outcomes")
    notes_cmd.add_argument("--date", required=True, help="target date in YYYY-MM-DD")
    notes_cmd.add_argument("--day", required=True, type=int, help="day number in daily_notes.md")
    notes_cmd.add_argument("--notes-file", default="daily_notes.md", help="path to daily notes markdown")
    notes_cmd.add_argument("--source", default=None, help="filter by source")

    eval_cmd = review_sub.add_parser("evaluate-exit", help="Evaluate buyback exit floor for an item")
    eval_cmd.add_argument("--source", required=True, help="item source")
    eval_cmd.add_argument("--item-url", required=True, help="item url")
    eval_cmd.add_argument("--item-category", default=None, choices=BUYBACK_ITEM_CATEGORIES, help="override item category")
    eval_cmd.add_argument("--save-note", action="store_true", help="append short exit evaluation summary to review note")
    eval_cmd.add_argument("--format", default="human", choices=("human", "json", "tsv"), help="output format")

    item_category_check_cmd = review_sub.add_parser("item-category-check", help="Show item_category schema and fill status")
    item_category_check_cmd.add_argument("--format", default="human", choices=("human", "json"), help="output format")

    review_ui_cmd = review_sub.add_parser("ui", help="Run local review UI for item_category updates")
    review_ui_cmd.add_argument("--host", default="127.0.0.1", help="bind host")
    review_ui_cmd.add_argument("--port", type=int, default=8765, help="bind port")

    buyback = sub.add_parser("buyback", help="Buyback support operations")
    buyback_sub = buyback.add_subparsers(dest="buyback_command", required=True)

    buyback_config = buyback_sub.add_parser("config", help="Show buyback configuration")
    buyback_config_sub = buyback_config.add_subparsers(dest="buyback_config_command", required=True)
    buyback_config_show = buyback_config_sub.add_parser("show", help="Show current buyback settings")
    buyback_config_show.add_argument("--format", default="human", choices=("human", "json", "tsv"), help="output format")

    buyback_shop = sub.add_parser("buyback-shop", help="Buyback shop master operations")
    shop_sub = buyback_shop.add_subparsers(dest="buyback_shop_command", required=True)

    shop_add = shop_sub.add_parser("add", help="Add buyback shop")
    shop_add.add_argument("--shop-name", required=True, help="shop name")
    shop_add.add_argument("--accepts-sealed", action="store_true", help="shop accepts sealed items")
    shop_add.add_argument("--accepts-opened-unused", action="store_true", help="shop accepts opened unused items")
    shop_add.add_argument("--no-accepts-used", action="store_true", help="shop does not accept used items")
    shop_add.add_argument("--supports-grade-pricing", action="store_true", help="shop uses grade pricing")
    shop_add.add_argument("--supports-junk", action="store_true", help="shop accepts junk items")
    shop_add.add_argument("--notes", default=None, help="optional notes")
    shop_add.add_argument("--inactive", action="store_true", help="create as inactive shop")

    shop_list = shop_sub.add_parser("list", help="List buyback shops")
    shop_list.add_argument("--active-only", action="store_true", help="show active shops only")
    shop_list.add_argument("--format", default="human", choices=("human", "json"), help="output format")

    shop_update = shop_sub.add_parser("update", help="Update buyback shop")
    shop_update.add_argument("--shop", required=True, help="shop id")
    shop_update.add_argument("--shop-name", default=None, help="new shop name")
    shop_update.add_argument("--accepts-sealed", action="store_true", default=None, help="enable sealed support")
    shop_update.add_argument("--no-accepts-sealed", action="store_true", default=None, help="disable sealed support")
    shop_update.add_argument("--accepts-opened-unused", action="store_true", default=None, help="enable opened unused support")
    shop_update.add_argument("--no-accepts-opened-unused", action="store_true", default=None, help="disable opened unused support")
    shop_update.add_argument("--accepts-used", action="store_true", default=None, help="enable used support")
    shop_update.add_argument("--no-accepts-used", action="store_true", default=None, help="disable used support")
    shop_update.add_argument("--supports-grade-pricing", action="store_true", default=None, help="enable grade pricing support")
    shop_update.add_argument("--no-supports-grade-pricing", action="store_true", default=None, help="disable grade pricing support")
    shop_update.add_argument("--supports-junk", action="store_true", default=None, help="enable junk support")
    shop_update.add_argument("--no-supports-junk", action="store_true", default=None, help="disable junk support")
    shop_update.add_argument("--notes", default=None, help="update notes")
    shop_update.add_argument("--active", action="store_true", default=None, help="mark active")
    shop_update.add_argument("--inactive", action="store_true", default=None, help="mark inactive")

    buyback_quote = sub.add_parser("buyback-quote", help="Buyback quote operations")
    quote_sub = buyback_quote.add_subparsers(dest="buyback_quote_command", required=True)

    quote_set = quote_sub.add_parser("set", help="Insert buyback quote")
    quote_set.add_argument("--source", required=True, help="item source")
    quote_set.add_argument("--item-url", required=True, help="item url")
    quote_set.add_argument("--shop", required=True, help="shop name or id")
    quote_set.add_argument("--category", required=True, choices=BUYBACK_ITEM_CATEGORIES, help="item category for this quote")
    quote_set.add_argument("--min", required=True, type=int, dest="quoted_price_min", help="quoted price min")
    quote_set.add_argument("--max", type=int, default=None, dest="quoted_price_max", help="quoted price max")
    quote_set.add_argument("--condition-assumption", default=None, help="condition assumption for this quote")
    quote_set.add_argument("--source-url", default=None, help="source url for quote")
    quote_set.add_argument("--notes", default=None, help="notes")
    quote_set.add_argument("--quote-checked-at", default=None, help="checked at in ISO8601")

    quote_list = quote_sub.add_parser("list", help="List buyback quotes for an item")
    quote_list.add_argument("--source", required=True, help="item source")
    quote_list.add_argument("--item-url", required=True, help="item url")
    quote_list.add_argument("--format", default="human", choices=("human", "json"), help="output format")

    quote_import = quote_sub.add_parser("import", help="Import buyback quotes from CSV or TSV")
    quote_import.add_argument("--input", required=True, help="input file path")
    quote_import.add_argument("--format", default="tsv", choices=("tsv", "csv"), help="input format")

    quote_fetch_iosys = quote_sub.add_parser("fetch-iosys", help="Fetch IOSYS iPhone buyback quotes")
    quote_fetch_iosys.add_argument("--source-url", required=True, help="IOSYS iPhone buyback table URL")
    quote_fetch_iosys.add_argument("--format", default="human", choices=("human", "json"), help="output format")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    settings = Settings.load(config_path=args.config, env_path=args.env)
    repo = ItemRepository(settings.app.db_path)

    if args.command == "run-once":
        service = MonitorService(
            settings=settings,
            fetcher=ScraplingFetcher(timeout_seconds=settings.app.fetch_timeout_seconds),
            extractor=RuleBasedExtractor(),
            repository=repo,
            notifier=TelegramNotifier(mode=settings.app.notification_mode),
        )
        stats = service.run_once()
        logging.getLogger(__name__).info(
            "done fetched=%s excluded=%s notified=%s errors=%s",
            stats.fetched,
            stats.excluded,
            stats.notified,
            stats.errors,
        )
        return 0

    if args.command == "review-status" and args.review_command == "set":
        ok = repo.update_review_status(args.source, args.item_url, args.status, review_note=args.note)
        if not ok:
            logging.getLogger(__name__).error("item not found: source=%s item_url=%s", args.source, args.item_url)
            return 1
        if args.item_category:
            repo.update_item_category(args.source, args.item_url, args.item_category)
        print(f"updated: source={args.source} item_url={args.item_url} review_status={args.status}")
        return 0

    if args.command == "review-status" and args.review_command == "list":
        rows = repo.list_recent_items(
            limit=args.limit,
            source=args.source,
            review_status=args.status,
            missing_item_category=args.missing_item_category,
            notified_only=args.notified_only,
        )
        if args.with_exit_eval or args.with_buyback_floor:
            service = BuybackEvaluationService(settings=settings, repository=repo)
            rows = _attach_exit_evaluation(rows, service)
        content = _render_recent_items(
            rows,
            args.format,
            with_exit_eval=args.with_exit_eval,
            with_buyback_floor=args.with_buyback_floor,
        )
        _emit_output(content, args.output)
        return 0

    if args.command == "review-status" and args.review_command == "item-category-check":
        content = _render_item_category_check(repo.summarize_item_category_state(), args.format)
        _emit_output(content, None)
        return 0

    if args.command == "review-status" and args.review_command == "ui":
        run_review_ui(repository=repo, host=args.host, port=args.port)
        return 0

    if args.command == "review-status" and args.review_command == "outcome-set":
        ok = repo.update_outcome(
            args.source,
            args.item_url,
            args.outcome,
            exit_channel=args.exit_channel,
            actual_sale_price=args.sale_price,
            outcome_note=args.note,
        )
        if not ok:
            logging.getLogger(__name__).error("item not found: source=%s item_url=%s", args.source, args.item_url)
            return 1
        print(
            f"updated: source={args.source} item_url={args.item_url} outcome_status={args.outcome} "
            f"exit_channel={args.exit_channel or '-'} sale_price={args.sale_price if args.sale_price is not None else '-'}"
        )
        return 0

    if args.command == "review-status" and args.review_command == "summary":
        summary = repo.summarize_review_status(source=args.source, review_status=args.status, timeseries=args.timeseries)
        content = _render_summary(summary, args.format)
        _emit_output(content, args.output)
        return 0

    if args.command == "review-status" and args.review_command == "performance":
        summary = repo.summarize_outcomes(source=args.source, exit_channel=args.exit_channel)
        content = _render_performance(summary, args.format)
        _emit_output(content, args.output)
        return 0

    if args.command == "review-status" and args.review_command == "daily-notes-sync":
        rows = repo.list_daily_note_items(target_date=args.date, source=args.source)
        content = _build_daily_notes_section(args.day, args.date, rows)
        path = Path(args.notes_file)
        updated = _upsert_day_section(path, args.day, content)
        path.write_text(updated, encoding="utf-8")
        print(f"written: {path}")
        return 0

    if args.command == "review-status" and args.review_command == "evaluate-exit":
        service = BuybackEvaluationService(settings=settings, repository=repo)
        result = service.evaluate_exit(args.source, args.item_url, item_category_override=args.item_category)
        comparison = _build_exit_actual_comparison(repo, result.source, result.item_url, result.conservative_exit_price, result.max_purchase_price)
        if args.save_note:
            ok = repo.append_review_note(args.source, args.item_url, _build_exit_eval_note_summary(result, comparison))
            if not ok:
                logging.getLogger(__name__).error("item not found: source=%s item_url=%s", args.source, args.item_url)
                return 1
        content = _render_exit_evaluation(result, args.format, comparison=comparison)
        _emit_output(content, None)
        return 0

    if args.command == "buyback" and args.buyback_command == "config" and args.buyback_config_command == "show":
        content = _render_buyback_config(settings, args.format)
        _emit_output(content, None)
        return 0

    if args.command == "buyback-shop" and args.buyback_shop_command == "add":
        shop_id = repo.add_buyback_shop(
            shop_name=args.shop_name,
            accepts_sealed=args.accepts_sealed,
            accepts_opened_unused=args.accepts_opened_unused,
            accepts_used=not args.no_accepts_used,
            supports_grade_pricing=args.supports_grade_pricing,
            supports_junk=args.supports_junk,
            notes=args.notes,
            is_active=not args.inactive,
        )
        print(f"created: shop_id={shop_id} shop_name={args.shop_name}")
        return 0

    if args.command == "buyback-shop" and args.buyback_shop_command == "list":
        rows = repo.list_buyback_shops(active_only=args.active_only)
        content = _render_buyback_shops(rows, args.format)
        _emit_output(content, None)
        return 0

    if args.command == "buyback-shop" and args.buyback_shop_command == "update":
        fields = _build_buyback_shop_update_fields(args)
        ok = repo.update_buyback_shop(int(args.shop), **fields)
        if not ok:
            logging.getLogger(__name__).error("shop not found or no updates: shop=%s", args.shop)
            return 1
        print(f"updated: shop_id={args.shop}")
        return 0

    if args.command == "buyback-quote" and args.buyback_quote_command == "set":
        shop_id = repo.resolve_buyback_shop_id(args.shop)
        if shop_id is None:
            logging.getLogger(__name__).error("shop not found: shop=%s", args.shop)
            return 1
        quote_id = repo.insert_buyback_quote(
            source=args.source,
            item_url=args.item_url,
            shop_id=shop_id,
            item_category=args.category,
            quoted_price_min=args.quoted_price_min,
            quoted_price_max=args.quoted_price_max,
            condition_assumption=args.condition_assumption,
            source_url=args.source_url,
            notes=args.notes,
            quote_checked_at=args.quote_checked_at,
        )
        print(f"created: quote_id={quote_id} shop_id={shop_id} item_url={args.item_url}")
        return 0

    if args.command == "buyback-quote" and args.buyback_quote_command == "list":
        rows = repo.list_buyback_quotes(args.source, args.item_url)
        rows = _attach_quote_staleness(rows, stale_quote_days=settings.buyback.stale_quote_days)
        content = _render_buyback_quotes(rows, args.format)
        _emit_output(content, None)
        return 0

    if args.command == "buyback-quote" and args.buyback_quote_command == "import":
        inserted = _import_buyback_quotes(
            repo=repo,
            input_path=args.input,
            input_format=args.format,
        )
        print(f"imported: {inserted}")
        return 0

    if args.command == "buyback-quote" and args.buyback_quote_command == "fetch-iosys":
        service = IosysBuybackService(
            fetcher=ScraplingFetcher(timeout_seconds=settings.app.fetch_timeout_seconds),
            repository=repo,
        )
        try:
            summary = service.fetch_and_store(source_url=args.source_url)
        except Exception as exc:
            logging.getLogger(__name__).exception("iosys fetch failed: url=%s err=%s", args.source_url, exc)
            return 1
        print(_render_iosys_fetch_summary(summary, args.format))
        return 0

    return 0


def _render_recent_items(
    rows: list[dict],
    output_format: str,
    with_exit_eval: bool = False,
    with_buyback_floor: bool = False,
) -> str:
    if not rows:
        if output_format == "json":
            return "[]"
        return "no items"
    fields = [
        "source",
        "review_status",
        "review_note",
        "exit_channel",
        "outcome_status",
        "actual_sale_price",
        "actual_profit",
        "outcome_note",
        "listed_price",
        "estimated_profit",
        "risk_score",
        "fetched_at",
        "item_category_hint",
        "title",
        "item_url",
    ]
    if with_buyback_floor:
        fields.extend(
            [
                "buyback_floor",
                "floor_gap",
                "buyback_decision",
                "buyback_stale_quote_found",
            ]
        )
    if with_exit_eval:
        fields.extend(
            [
                "item_category",
                "conservative_exit_price",
                "max_purchase_price",
                "decision",
                "stale_quote_found",
            ]
        )
    if output_format == "json":
        return json.dumps(rows, ensure_ascii=False)
    if output_format == "human":
        lines = []
        for idx, r in enumerate(rows, start=1):
            lines.append(
                f"[{idx}] {r['title']} | status={r['review_status']} | hint={r.get('item_category_hint') or '-'} | category={r.get('item_category') or '-'}"
            )
            lines.append(
                f"    price={r['listed_price']} profit={r['estimated_profit']} risk={r['risk_score']} fetched_at={r['fetched_at']}"
            )
            if with_buyback_floor:
                lines.append(
                    "    "
                    f"buyback_floor={r.get('buyback_floor') if r.get('buyback_floor') is not None else '-'} "
                    f"floor_gap={_format_signed(r.get('floor_gap'))} "
                    f"decision={r.get('buyback_decision') or '-'} "
                    f"stale_quote_found={_bool_text(r.get('buyback_stale_quote_found'))}"
                )
            lines.append(f"    url={r['item_url']}")
            if r.get("review_note"):
                lines.append(f"    note={r['review_note']}")
            if with_exit_eval:
                lines.append(
                    "    "
                    f"exit_eval: item_category={r.get('item_category') or '-'} "
                    f"conservative_exit_price={r.get('conservative_exit_price') or '-'} "
                    f"max_purchase_price={r.get('max_purchase_price') or '-'} "
                    f"decision={r.get('decision') or '-'} "
                    f"stale_quote_found={_bool_text(r.get('stale_quote_found'))}"
                )
        return "\n".join(lines)
    if output_format == "csv":
        buf = StringIO()
        writer = csv.DictWriter(buf, fieldnames=fields)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in fields})
        return buf.getvalue().strip()
    header = "source\treview_status\treview_note\texit_channel\toutcome_status\tactual_sale_price\tactual_profit\toutcome_note\tprice\tprofit\trisk\tfetched_at\titem_category_hint\ttitle\titem_url"
    if with_buyback_floor:
        header += "\tbuyback_floor\tfloor_gap\tbuyback_decision\tbuyback_stale_quote_found"
    if with_exit_eval:
        header += "\titem_category\tconservative_exit_price\tmax_purchase_price\tdecision\tstale_quote_found"
    lines = [header]
    for r in rows:
        line = (
            f"{r['source']}\t{r['review_status']}\t{r.get('review_note') or ''}\t{r.get('exit_channel') or ''}\t"
            f"{r.get('outcome_status') or ''}\t{r.get('actual_sale_price') or ''}\t{r.get('actual_profit') or ''}\t"
            f"{r.get('outcome_note') or ''}\t{r['listed_price']}\t{r['estimated_profit']}\t{r['risk_score']}\t{r['fetched_at']}\t{r.get('item_category_hint') or ''}\t{r['title']}\t{r['item_url']}"
        )
        if with_buyback_floor:
            line += (
                f"\t{r.get('buyback_floor') if r.get('buyback_floor') is not None else ''}\t"
                f"{r.get('floor_gap') if r.get('floor_gap') is not None else ''}\t"
                f"{r.get('buyback_decision') or ''}\t"
                f"{_bool_text(r.get('buyback_stale_quote_found'))}"
            )
        if with_exit_eval:
            line += (
                f"\t{r.get('item_category') or ''}\t{r.get('conservative_exit_price') or ''}\t"
                f"{r.get('max_purchase_price') or ''}\t{r.get('decision') or ''}\t"
                f"{_bool_text(r.get('stale_quote_found'))}"
            )
        lines.append(line)
    return "\n".join(lines)


def _render_item_category_check(payload: dict, output_format: str) -> str:
    if output_format == "json":
        return json.dumps(payload, ensure_ascii=False)
    distribution = payload.get("item_category_distribution", {})
    return "\n".join(
        [
            f"item_category_column_exists: {'yes' if payload.get('item_category_column_exists') else 'no'}",
            f"items_total: {payload.get('items_total', 0)}",
            f"item_category_missing_count: {payload.get('item_category_missing_count', 0)}",
            f"item_category_filled_count: {payload.get('item_category_filled_count', 0)}",
            f"item_category_distribution: used={distribution.get('used', 0)} opened_unused={distribution.get('opened_unused', 0)} null={distribution.get('null', 0)}",
            f"opened_unused_hint_count: {payload.get('opened_unused_hint_count', 0)}",
        ]
    )


def _render_summary(summary: dict, output_format: str) -> str:
    ordered = ["pending", "watched", "good", "bad", "bought"]
    status_avg = summary.get("status_average_estimated_profit", {})
    rows = []
    for s in ordered:
        rows.append(
            {
                "review_status": s,
                "count": summary.get(f"{s}_count", 0),
                "average_estimated_profit": status_avg.get(s),
            }
        )
    if output_format == "json":
        payload = {
            "total_items": summary.get("total_items", 0),
            "pending_count": summary.get("pending_count", 0),
            "watched_count": summary.get("watched_count", 0),
            "good_count": summary.get("good_count", 0),
            "bad_count": summary.get("bad_count", 0),
            "bought_count": summary.get("bought_count", 0),
            "good_rate": summary.get("good_rate", 0.0),
            "bad_rate": summary.get("bad_rate", 0.0),
            "bought_rate": summary.get("bought_rate", 0.0),
            "average_estimated_profit": summary.get("average_estimated_profit", 0.0),
            "status_average_estimated_profit": status_avg,
            "source_breakdown": summary.get("source_breakdown", {}),
            "candidate_total_items": summary.get("candidate_total_items", 0),
            "candidate_good_rate": summary.get("candidate_good_rate", 0.0),
            "candidate_bad_rate": summary.get("candidate_bad_rate", 0.0),
            "candidate_bought_rate": summary.get("candidate_bought_rate", 0.0),
            "timeseries_daily": summary.get("timeseries_daily", []),
            "timeseries_weekly": summary.get("timeseries_weekly", []),
            "source_timeseries_daily": summary.get("source_timeseries_daily", {}),
            "source_timeseries_weekly": summary.get("source_timeseries_weekly", {}),
        }
        return json.dumps(payload, ensure_ascii=False)
    if output_format == "csv":
        buf = StringIO()
        writer = csv.DictWriter(buf, fieldnames=["review_status", "count", "average_estimated_profit"])
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
        metrics = [
            f"total_items,{summary.get('total_items', 0)}",
            f"good_rate,{summary.get('good_rate', 0.0)}",
            f"bad_rate,{summary.get('bad_rate', 0.0)}",
            f"bought_rate,{summary.get('bought_rate', 0.0)}",
            f"average_estimated_profit,{summary.get('average_estimated_profit', 0.0)}",
            f"candidate_total_items,{summary.get('candidate_total_items', 0)}",
            f"candidate_good_rate,{summary.get('candidate_good_rate', 0.0)}",
            f"candidate_bad_rate,{summary.get('candidate_bad_rate', 0.0)}",
            f"candidate_bought_rate,{summary.get('candidate_bought_rate', 0.0)}",
        ]
        source_lines = ["source,total_items,good_count,bad_count,bought_count,good_rate,bad_rate,bought_rate,average_estimated_profit"]
        for src, m in sorted(summary.get("source_breakdown", {}).items()):
            source_lines.append(
                f"{src},{m.get('total_items',0)},{m.get('good_count',0)},{m.get('bad_count',0)},{m.get('bought_count',0)},"
                f"{m.get('good_rate',0.0)},{m.get('bad_rate',0.0)},{m.get('bought_rate',0.0)},{m.get('average_estimated_profit',0.0)}"
            )
        daily_lines = ["daily_bucket,total_items,good_count,bad_count,bought_count,good_rate,bad_rate,bought_rate,average_estimated_profit"]
        for row in summary.get("timeseries_daily", []):
            daily_lines.append(
                f"{row.get('bucket')},{row.get('total_items',0)},{row.get('good_count',0)},{row.get('bad_count',0)},{row.get('bought_count',0)},"
                f"{row.get('good_rate',0.0)},{row.get('bad_rate',0.0)},{row.get('bought_rate',0.0)},{row.get('average_estimated_profit',0.0)}"
            )
        weekly_lines = ["weekly_bucket,total_items,good_count,bad_count,bought_count,good_rate,bad_rate,bought_rate,average_estimated_profit"]
        for row in summary.get("timeseries_weekly", []):
            weekly_lines.append(
                f"{row.get('bucket')},{row.get('total_items',0)},{row.get('good_count',0)},{row.get('bad_count',0)},{row.get('bought_count',0)},"
                f"{row.get('good_rate',0.0)},{row.get('bad_rate',0.0)},{row.get('bought_rate',0.0)},{row.get('average_estimated_profit',0.0)}"
            )
        return (
            buf.getvalue().strip()
            + "\n"
            + "\n".join(metrics)
            + "\n"
            + "\n".join(source_lines)
            + "\n"
            + "\n".join(daily_lines)
            + "\n"
            + "\n".join(weekly_lines)
        )
    lines = [
        f"total_items\t{summary.get('total_items', 0)}",
        f"pending_count\t{summary.get('pending_count', 0)}",
        f"watched_count\t{summary.get('watched_count', 0)}",
        f"good_count\t{summary.get('good_count', 0)}",
        f"bad_count\t{summary.get('bad_count', 0)}",
        f"bought_count\t{summary.get('bought_count', 0)}",
        f"good_rate\t{summary.get('good_rate', 0.0)}",
        f"bad_rate\t{summary.get('bad_rate', 0.0)}",
        f"bought_rate\t{summary.get('bought_rate', 0.0)}",
        f"average_estimated_profit\t{summary.get('average_estimated_profit', 0.0)}",
        f"candidate_total_items\t{summary.get('candidate_total_items', 0)}",
        f"candidate_good_rate\t{summary.get('candidate_good_rate', 0.0)}",
        f"candidate_bad_rate\t{summary.get('candidate_bad_rate', 0.0)}",
        f"candidate_bought_rate\t{summary.get('candidate_bought_rate', 0.0)}",
        "status\tcount\taverage_estimated_profit",
    ]
    for r in rows:
        lines.append(f"{r['review_status']}\t{r['count']}\t{r['average_estimated_profit']}")
    lines.append("source\ttotal_items\tgood_count\tbad_count\tbought_count\tgood_rate\tbad_rate\tbought_rate\taverage_estimated_profit")
    for src, m in sorted(summary.get("source_breakdown", {}).items()):
        lines.append(
            f"{src}\t{m.get('total_items',0)}\t{m.get('good_count',0)}\t{m.get('bad_count',0)}\t{m.get('bought_count',0)}\t"
            f"{m.get('good_rate',0.0)}\t{m.get('bad_rate',0.0)}\t{m.get('bought_rate',0.0)}\t{m.get('average_estimated_profit',0.0)}"
        )
    lines.append("daily_bucket\ttotal_items\tgood_count\tbad_count\tbought_count\tgood_rate\tbad_rate\tbought_rate\taverage_estimated_profit")
    for row in summary.get("timeseries_daily", []):
        lines.append(
            f"{row.get('bucket')}\t{row.get('total_items',0)}\t{row.get('good_count',0)}\t{row.get('bad_count',0)}\t{row.get('bought_count',0)}\t"
            f"{row.get('good_rate',0.0)}\t{row.get('bad_rate',0.0)}\t{row.get('bought_rate',0.0)}\t{row.get('average_estimated_profit',0.0)}"
        )
    lines.append("weekly_bucket\ttotal_items\tgood_count\tbad_count\tbought_count\tgood_rate\tbad_rate\tbought_rate\taverage_estimated_profit")
    for row in summary.get("timeseries_weekly", []):
        lines.append(
            f"{row.get('bucket')}\t{row.get('total_items',0)}\t{row.get('good_count',0)}\t{row.get('bad_count',0)}\t{row.get('bought_count',0)}\t"
            f"{row.get('good_rate',0.0)}\t{row.get('bad_rate',0.0)}\t{row.get('bought_rate',0.0)}\t{row.get('average_estimated_profit',0.0)}"
        )
    return "\n".join(lines)


def _emit_output(content: str, output_path: str | None) -> None:
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content + "\n", encoding="utf-8")
        print(f"written: {path}")
        return
    try:
        sys.stdout.write(content + "\n")
    except UnicodeEncodeError:
        buffer = getattr(sys.stdout, "buffer", None)
        if buffer is not None:
            encoding = sys.stdout.encoding or "utf-8"
            buffer.write((content + "\n").encode(encoding, errors="replace"))
            buffer.flush()
            return
        sys.stdout.write((content + "\n").encode("ascii", errors="replace").decode("ascii"))


def _render_performance(summary: dict, output_format: str) -> str:
    status_order = ("passed", "bought", "sold", "buyback_done", "loss")
    rows = []
    for status in status_order:
        current = summary.get("status_breakdown", {}).get(status, {})
        rows.append(
            {
                "outcome_status": status,
                "count": current.get("count", 0),
                "average_actual_profit": current.get("average_actual_profit"),
            }
        )
    if output_format == "json":
        return json.dumps(summary, ensure_ascii=False)
    if output_format == "csv":
        buf = StringIO()
        writer = csv.DictWriter(buf, fieldnames=["outcome_status", "count", "average_actual_profit"])
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        metrics = [
            f"total_items,{summary.get('total_items', 0)}",
            f"realized_count,{summary.get('realized_count', 0)}",
            f"realized_average_actual_profit,{summary.get('realized_average_actual_profit', 0.0)}",
            f"realized_total_profit,{summary.get('realized_total_profit', 0)}",
            f"sold_count,{summary.get('sold_count', 0)}",
            f"buyback_done_count,{summary.get('buyback_done_count', 0)}",
            f"loss_count,{summary.get('loss_count', 0)}",
        ]
        channel_lines = ["exit_channel,count,average_actual_profit,profitable_count,profitable_rate"]
        for channel, data in sorted(summary.get("channel_breakdown", {}).items()):
            channel_lines.append(
                f"{channel},{data.get('count',0)},{data.get('average_actual_profit',0.0)},{data.get('profitable_count',0)},{data.get('profitable_rate',0.0)}"
            )
        return buf.getvalue().strip() + "\n" + "\n".join(metrics) + "\n" + "\n".join(channel_lines)

    lines = [
        f"total_items\t{summary.get('total_items', 0)}",
        f"realized_count\t{summary.get('realized_count', 0)}",
        f"average_actual_profit\t{summary.get('average_actual_profit', 0.0)}",
        f"realized_average_actual_profit\t{summary.get('realized_average_actual_profit', 0.0)}",
        f"realized_total_profit\t{summary.get('realized_total_profit', 0)}",
        f"sold_count\t{summary.get('sold_count', 0)}",
        f"buyback_done_count\t{summary.get('buyback_done_count', 0)}",
        f"passed_count\t{summary.get('passed_count', 0)}",
        f"loss_count\t{summary.get('loss_count', 0)}",
        f"sold_rate\t{summary.get('sold_rate', 0.0)}",
        f"buyback_done_rate\t{summary.get('buyback_done_rate', 0.0)}",
        f"loss_rate\t{summary.get('loss_rate', 0.0)}",
        "outcome_status\tcount\taverage_actual_profit",
    ]
    for row in rows:
        lines.append(f"{row['outcome_status']}\t{row['count']}\t{row['average_actual_profit']}")
    lines.append("exit_channel\tcount\taverage_actual_profit\tprofitable_count\tprofitable_rate")
    for channel, data in sorted(summary.get("channel_breakdown", {}).items()):
        lines.append(
            f"{channel}\t{data.get('count',0)}\t{data.get('average_actual_profit')}\t{data.get('profitable_count',0)}\t{data.get('profitable_rate',0.0)}"
        )
    return "\n".join(lines)


def _render_buyback_shops(rows: list[dict], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(rows, ensure_ascii=False)
    if not rows:
        return "no shops"
    lines = []
    for row in rows:
        lines.append(
            f"[{row['id']}] {row['shop_name']} "
            f"active={'yes' if row['is_active'] else 'no'} "
            f"sealed={'yes' if row['accepts_sealed'] else 'no'} "
            f"opened_unused={'yes' if row['accepts_opened_unused'] else 'no'} "
            f"used={'yes' if row['accepts_used'] else 'no'} "
            f"grade={'yes' if row['supports_grade_pricing'] else 'no'} "
            f"junk={'yes' if row['supports_junk'] else 'no'} "
            f"notes={row.get('notes') or '-'}"
        )
    return "\n".join(lines)


def _render_buyback_quotes(rows: list[dict], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(rows, ensure_ascii=False)
    if not rows:
        return "no quotes"
    lines = []
    for row in rows:
        lines.append(
            f"[{row['id']}] {row['shop_name']} category={row['item_category']} "
            f"min={row['quoted_price_min']} max={row.get('quoted_price_max') or '-'} "
            f"checked_at={row['quote_checked_at']} active={'yes' if row['shop_is_active'] else 'no'} "
            f"stale={_bool_text(row.get('stale'))} age_days={row.get('quote_age_days') if row.get('quote_age_days') is not None else '-'} "
            f"condition={row.get('condition_assumption') or '-'}"
        )
    return "\n".join(lines)


def _render_iosys_fetch_summary(summary, output_format: str) -> str:
    if output_format == "json":
        return json.dumps(summary.to_dict(), ensure_ascii=False)
    parts = [
        f"saved={summary.saved_count}",
        f"skipped={summary.skipped_count}",
        f"unmatched_quote_rows={summary.unmatched_quote_rows}",
        f"expanded_item_count={summary.expanded_item_count}",
        f"item_category_missing_count={summary.item_category_missing_count}",
    ]
    if getattr(summary, "parser_error_count", 0) or getattr(summary, "insert_error_count", 0):
        parts.append(f"parser_errors={summary.parser_error_count}")
        parts.append(f"insert_errors={summary.insert_error_count}")
    lines = [" ".join(parts)]
    if getattr(summary, "unmatched_reason_counts", None):
        reason_text = ", ".join(f"{key}={value}" for key, value in sorted(summary.unmatched_reason_counts.items()))
        lines.append(f"unmatched_reasons: {reason_text}")
    if getattr(summary, "unmatched_examples", None):
        lines.append("unmatched_examples:")
        for example in summary.unmatched_examples:
            lines.append(
                "  "
                f"model={example.model_name_raw} carrier={example.carrier_type} "
                f"storage={example.storage_gb} category={example.item_category} reason={example.reason}"
            )
    return "\n".join(lines)


def _render_exit_evaluation(result, output_format: str, comparison: dict | None = None) -> str:
    payload = {
        "source": result.source,
        "item_url": result.item_url,
        "item_category": result.item_category,
        "compatible_buyback_routes": result.compatible_buyback_routes,
        "incompatible_buyback_routes": result.incompatible_buyback_routes,
        "conservative_exit_price": result.conservative_exit_price,
        "max_purchase_price": result.max_purchase_price,
        "has_buyback_floor": result.has_buyback_floor,
        "decision": result.decision,
        "risk_flags": result.risk_flags,
        "reason_summary": result.reason_summary,
        "estimated_fees": result.estimated_fees,
        "estimated_shipping_cost": result.estimated_shipping_cost,
        "estimated_buyback_haircut": result.estimated_buyback_haircut,
        "target_profit": result.target_profit,
        "stale_quote_found": result.stale_quote_found,
    }
    if comparison:
        payload.update(comparison)
    if output_format == "json":
        return json.dumps(payload, ensure_ascii=False)
    if output_format == "tsv":
        return "\n".join(f"{key}\t{value}" for key, value in payload.items())
    lines = [
        f"source: {result.source}",
        f"item_url: {result.item_url}",
        f"item_category: {result.item_category or '-'}",
        f"compatible_buyback_routes: {', '.join(result.compatible_buyback_routes) if result.compatible_buyback_routes else '-'}",
        f"incompatible_buyback_routes: {', '.join(result.incompatible_buyback_routes) if result.incompatible_buyback_routes else '-'}",
        f"conservative_exit_price: {result.conservative_exit_price if result.conservative_exit_price is not None else '-'}",
        f"max_purchase_price: {result.max_purchase_price if result.max_purchase_price is not None else '-'}",
        f"has_buyback_floor: {'yes' if result.has_buyback_floor else 'no'}",
        f"decision: {result.decision}",
        f"risk_flags: {', '.join(result.risk_flags) if result.risk_flags else '-'}",
        f"stale_quote_found: {'yes' if result.stale_quote_found else 'no'}",
        f"reason_summary: {result.reason_summary}",
    ]
    if comparison:
        lines.extend(
            [
                f"actual_sale_price: {comparison.get('actual_sale_price') if comparison.get('actual_sale_price') is not None else '-'}",
                f"actual_vs_conservative_exit_price: {comparison.get('actual_vs_conservative_exit_price') if comparison.get('actual_vs_conservative_exit_price') is not None else '-'}",
                f"actual_vs_max_purchase_price: {comparison.get('actual_vs_max_purchase_price') if comparison.get('actual_vs_max_purchase_price') is not None else '-'}",
            ]
        )
    return "\n".join(lines)


def _render_buyback_config(settings: Settings, output_format: str) -> str:
    payload = {
        "stale_quote_days": settings.buyback.stale_quote_days,
        "target_profit_yen": settings.buyback.target_profit_yen,
        "estimated_shipping_cost_yen": settings.buyback.estimated_shipping_cost_yen,
        "estimated_fee_yen": settings.buyback.estimated_fee_yen,
        "default_haircut_yen": settings.buyback.default_haircut_yen,
        "grade_pricing_extra_haircut_yen": settings.buyback.grade_pricing_extra_haircut_yen,
    }
    if output_format == "json":
        return json.dumps(payload, ensure_ascii=False)
    if output_format == "tsv":
        return "\n".join(f"{key}\t{value}" for key, value in payload.items())
    return "\n".join(f"{key}: {value}" for key, value in payload.items())


def _attach_exit_evaluation(rows: list[dict], service: BuybackEvaluationService) -> list[dict]:
    out: list[dict] = []
    for row in rows:
        current = dict(row)
        result = service.evaluate_exit(row["source"], row["item_url"])
        current["item_category"] = result.item_category
        current["conservative_exit_price"] = result.conservative_exit_price
        current["max_purchase_price"] = result.max_purchase_price
        current["decision"] = result.decision
        current["stale_quote_found"] = result.stale_quote_found
        purchase_cost = int(current.get("listed_price") or 0)
        current["buyback_floor"] = result.conservative_exit_price
        current["floor_gap"] = _diff_or_none(result.conservative_exit_price, purchase_cost)
        current["buyback_decision"] = result.decision
        current["buyback_stale_quote_found"] = result.stale_quote_found
        out.append(current)
    return out


def _format_signed(value) -> str:
    if value is None or value == "":
        return "-"
    value = int(value)
    return f"+{value}" if value > 0 else str(value)


def _build_exit_actual_comparison(
    repo: ItemRepository,
    source: str,
    item_url: str,
    conservative_exit_price: int | None,
    max_purchase_price: int | None,
) -> dict:
    ctx = repo.get_item_buyback_context(source, item_url)
    actual_sale_price = None if not ctx else ctx.get("actual_sale_price")
    return {
        "actual_sale_price": actual_sale_price,
        "actual_vs_conservative_exit_price": _diff_or_none(actual_sale_price, conservative_exit_price),
        "actual_vs_max_purchase_price": _diff_or_none(actual_sale_price, max_purchase_price),
    }


def _build_exit_eval_note_summary(result, comparison: dict | None) -> str:
    parts = [
        f"[exit-eval] cat={result.item_category or '-'}",
        f"floor={result.conservative_exit_price if result.conservative_exit_price is not None else '-'}",
        f"max_buy={result.max_purchase_price if result.max_purchase_price is not None else '-'}",
        f"decision={result.decision}",
    ]
    if result.stale_quote_found:
        parts.append("stale=yes")
    if comparison and comparison.get("actual_sale_price") is not None:
        parts.append(f"actual={comparison['actual_sale_price']}")
    return " ".join(parts)


def _attach_quote_staleness(rows: list[dict], stale_quote_days: int) -> list[dict]:
    out: list[dict] = []
    for row in rows:
        current = dict(row)
        current["quote_age_days"] = compute_quote_age_days(row.get("quote_checked_at"))
        current["stale"] = is_quote_stale(row.get("quote_checked_at"), stale_quote_days)
        out.append(current)
    return out


def _import_buyback_quotes(repo: ItemRepository, input_path: str, input_format: str) -> int:
    delimiter = "\t" if input_format == "tsv" else ","
    inserted = 0
    with Path(input_path).open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh, delimiter=delimiter)
        for row in reader:
            if not row:
                continue
            source = (row.get("source") or "").strip()
            item_url = (row.get("item_url") or "").strip()
            shop = (row.get("shop") or row.get("shop_name") or "").strip()
            category = (row.get("category") or row.get("item_category") or "").strip()
            quoted_price_min = _required_int(row.get("min") or row.get("quoted_price_min"), "min")
            quoted_price_max = _optional_int(row.get("max") or row.get("quoted_price_max"))
            if not source or not item_url or not shop or category not in BUYBACK_ITEM_CATEGORIES:
                raise ValueError("import row requires source,item_url,shop,category,min")
            shop_id = repo.resolve_buyback_shop_id(shop)
            if shop_id is None:
                raise ValueError(f"shop not found in import: {shop}")
            repo.insert_buyback_quote(
                source=source,
                item_url=item_url,
                shop_id=shop_id,
                item_category=category,
                quoted_price_min=quoted_price_min,
                quoted_price_max=quoted_price_max,
                condition_assumption=_blank_to_none(row.get("condition_assumption")),
                source_url=_blank_to_none(row.get("source_url")),
                notes=_blank_to_none(row.get("notes")),
                quote_checked_at=_blank_to_none(row.get("quote_checked_at")),
            )
            inserted += 1
    return inserted


def _build_daily_notes_section(day: int, target_date: str, rows: list[dict]) -> str:
    status_groups = {"good": [], "bad": [], "watched": [], "bought": []}
    memo_lines: list[str] = []
    section: list[str] = [
        f"## Day{day}（{target_date}）",
        "- [ ] 朝の実行を確認",
        "- [ ] 昼の実行を確認",
        "- [ ] 夜の実行を確認",
        _checkbox_line(bool(rows), "通知件数を記録（通知なしでも記録）"),
        _checkbox_line(any(r.get("review_status") and r.get("review_status") != "pending" for r in rows), "review_status を更新"),
        "",
        "### 通知記録",
        f"- 件数: {len(rows)}",
        "- 案件:",
    ]
    if not rows:
        section.append("  - なし")
    for row in rows:
        section.extend(
            [
                f"  - URL: {row['item_url']}",
                f"    - 価格: {row['listed_price']:,}円",
                f"    - 想定粗利: {row['estimated_profit']:,}円",
                f"    - 通知理由: {_normalize_reason(row.get('notification_reason'))}",
            ]
        )
        item_id = _item_id_from_url(row["item_url"])
        status = row.get("review_status") or "pending"
        if status in status_groups and row.get("review_note"):
            status_groups[status].append((item_id, row["review_note"]))
        if row.get("outcome_note"):
            outcome_prefix = _format_outcome_prefix(row)
            memo_lines.append(f"{item_id}: {outcome_prefix}{row['outcome_note']}")
    section.extend(["", "### review_status 記録"])
    for status in ("good", "bad", "watched", "bought"):
        section.append(f"- {status}:")
        entries = status_groups[status]
        if not entries:
            section.append("  - なし")
        else:
            for item_id, note in entries:
                section.append(f"  - {item_id}")
                section.append(f"    - 判定理由: {note}")
        section.append("")
    section.append("### 気づきメモ")
    if memo_lines:
        section.extend(f"- {line}" for line in memo_lines)
    else:
        section.append("- なし")
    return "\n".join(section).rstrip() + "\n"


def _normalize_reason(reason: str | None) -> str:
    if not reason:
        return "DB未保存"
    m = re.search(r"target=([^,]+),", reason)
    if m:
        return m.group(1).strip()
    return reason


def _format_outcome_prefix(row: dict) -> str:
    outcome = row.get("outcome_status") or "none"
    channel = row.get("exit_channel")
    profit = row.get("actual_profit")
    parts = [outcome]
    if channel:
        parts.append(channel)
    if profit is not None:
        parts.append(f"実粗利 {profit:,}円")
    return " / ".join(parts) + " / "


def _item_id_from_url(item_url: str) -> str:
    return item_url.rstrip("/").split("/")[-1]


def _checkbox_line(checked: bool, label: str) -> str:
    mark = "x" if checked else " "
    return f"- [{mark}] {label}"


def _build_buyback_shop_update_fields(args) -> dict:
    fields: dict[str, object] = {}
    if args.shop_name is not None:
        fields["shop_name"] = args.shop_name
    if args.accepts_sealed:
        fields["accepts_sealed"] = True
    elif args.no_accepts_sealed:
        fields["accepts_sealed"] = False
    if args.accepts_opened_unused:
        fields["accepts_opened_unused"] = True
    elif args.no_accepts_opened_unused:
        fields["accepts_opened_unused"] = False
    if args.accepts_used:
        fields["accepts_used"] = True
    elif args.no_accepts_used:
        fields["accepts_used"] = False
    if args.supports_grade_pricing:
        fields["supports_grade_pricing"] = True
    elif args.no_supports_grade_pricing:
        fields["supports_grade_pricing"] = False
    if args.supports_junk:
        fields["supports_junk"] = True
    elif args.no_supports_junk:
        fields["supports_junk"] = False
    if args.notes is not None:
        fields["notes"] = args.notes
    if args.active:
        fields["is_active"] = True
    elif args.inactive:
        fields["is_active"] = False
    return fields


def _bool_text(value) -> str:
    return "yes" if value else "no"


def _diff_or_none(left, right) -> int | None:
    if left is None or right is None:
        return None
    return int(left) - int(right)


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def _optional_int(value) -> int | None:
    value = _blank_to_none(value)
    if value is None:
        return None
    return int(value)


def _required_int(value, field_name: str) -> int:
    value = _blank_to_none(value)
    if value is None:
        raise ValueError(f"import row requires {field_name}")
    return int(value)


def _upsert_day_section(path: Path, day: int, section: str) -> str:
    original = path.read_text(encoding="utf-8")
    normalized = original.replace("\r\n", "\n")
    pattern = re.compile(
        rf"(?ms)^[ \t]*## Day{day}（.*?）.*?(?=^[ \t]*## Day{day + 1}（|\\Z)"
    )
    if pattern.search(normalized):
        updated = pattern.sub(section.rstrip("\n"), normalized, count=1)
    else:
        if not normalized.endswith("\n"):
            normalized += "\n"
        updated = normalized + "\n" + section
    return updated


if __name__ == "__main__":
    raise SystemExit(main())
