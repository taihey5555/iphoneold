from __future__ import annotations

import argparse
import csv
import json
import logging
from io import StringIO
from pathlib import Path
from typing import Sequence

from app.config import Settings
from app.extractors.rule_based import RuleBasedExtractor
from app.notifiers import TelegramNotifier
from app.repositories import ItemRepository, ScraplingFetcher
from app.services import MonitorService

REVIEW_STATUSES = ("pending", "watched", "good", "bad", "bought")


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

    list_cmd = review_sub.add_parser("list", help="List recent items with review_status")
    list_cmd.add_argument("--limit", type=int, default=20, help="number of rows")
    list_cmd.add_argument("--source", default=None, help="filter by source")
    list_cmd.add_argument("--status", default=None, choices=REVIEW_STATUSES, help="filter by review status")
    list_cmd.add_argument("--format", default="tsv", choices=("tsv", "csv", "json"), help="output format")
    list_cmd.add_argument("--output", default=None, help="write output to file")

    summary_cmd = review_sub.add_parser("summary", help="Summary metrics by review_status")
    summary_cmd.add_argument("--source", default=None, help="filter by source")
    summary_cmd.add_argument("--status", default=None, choices=REVIEW_STATUSES, help="filter by review status")
    summary_cmd.add_argument("--timeseries", default="both", choices=("none", "daily", "weekly", "both"), help="timeseries interval")
    summary_cmd.add_argument("--format", default="tsv", choices=("tsv", "csv", "json"), help="output format")
    summary_cmd.add_argument("--output", default=None, help="write output to file")
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
        ok = repo.update_review_status(args.source, args.item_url, args.status)
        if not ok:
            logging.getLogger(__name__).error("item not found: source=%s item_url=%s", args.source, args.item_url)
            return 1
        print(f"updated: source={args.source} item_url={args.item_url} review_status={args.status}")
        return 0

    if args.command == "review-status" and args.review_command == "list":
        rows = repo.list_recent_items(limit=args.limit, source=args.source, review_status=args.status)
        content = _render_recent_items(rows, args.format)
        _emit_output(content, args.output)
        return 0

    if args.command == "review-status" and args.review_command == "summary":
        summary = repo.summarize_review_status(source=args.source, review_status=args.status, timeseries=args.timeseries)
        content = _render_summary(summary, args.format)
        _emit_output(content, args.output)
        return 0

    return 0


def _render_recent_items(rows: list[dict], output_format: str) -> str:
    if not rows:
        if output_format == "json":
            return "[]"
        return "no items"
    fields = ["source", "review_status", "listed_price", "estimated_profit", "risk_score", "fetched_at", "title", "item_url"]
    if output_format == "json":
        return json.dumps(rows, ensure_ascii=False)
    if output_format == "csv":
        buf = StringIO()
        writer = csv.DictWriter(buf, fieldnames=fields)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in fields})
        return buf.getvalue().strip()
    header = "source\treview_status\tprice\tprofit\trisk\tfetched_at\ttitle\titem_url"
    lines = [header]
    for r in rows:
        lines.append(f"{r['source']}\t{r['review_status']}\t{r['listed_price']}\t{r['estimated_profit']}\t{r['risk_score']}\t{r['fetched_at']}\t{r['title']}\t{r['item_url']}")
    return "\n".join(lines)


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
    print(content)


if __name__ == "__main__":
    raise SystemExit(main())
