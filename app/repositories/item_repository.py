from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.models import NormalizedFields, RawListing, ScoredItem


class ItemRepository:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS items (
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
                  review_status TEXT NOT NULL DEFAULT 'pending',
                  exclude_reason TEXT,
                  UNIQUE(source, item_url)
                )
                """
            )
            try:
                conn.execute("ALTER TABLE items ADD COLUMN review_status TEXT NOT NULL DEFAULT 'pending'")
            except sqlite3.OperationalError:
                pass
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS notification_history (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  source TEXT NOT NULL,
                  item_url TEXT NOT NULL,
                  dedupe_key TEXT,
                  similarity_key TEXT,
                  notified_price INTEGER,
                  notified_at TEXT NOT NULL
                )
                """
            )
            try:
                conn.execute("ALTER TABLE notification_history ADD COLUMN dedupe_key TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE notification_history ADD COLUMN similarity_key TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE notification_history ADD COLUMN notified_price INTEGER")
            except sqlite3.OperationalError:
                pass

    def upsert_scored_item(self, item: ScoredItem) -> None:
        raw = item.raw
        norm = item.normalized
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO items (
                  source, item_url, title, description, listed_price, shipping_fee, posted_at,
                  seller_name, image_urls_json, fetched_at, normalized_json, expected_resale_price,
                  estimated_profit, selling_fee, shipping_cost, risk_buffer, risk_score, risk_flags_json, review_status, exclude_reason
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source, item_url) DO UPDATE SET
                  title=excluded.title,
                  description=excluded.description,
                  listed_price=excluded.listed_price,
                  shipping_fee=excluded.shipping_fee,
                  posted_at=excluded.posted_at,
                  seller_name=excluded.seller_name,
                  image_urls_json=excluded.image_urls_json,
                  fetched_at=excluded.fetched_at,
                  normalized_json=excluded.normalized_json,
                  expected_resale_price=excluded.expected_resale_price,
                  estimated_profit=excluded.estimated_profit,
                  selling_fee=excluded.selling_fee,
                  shipping_cost=excluded.shipping_cost,
                  risk_buffer=excluded.risk_buffer,
                  risk_score=excluded.risk_score,
                  risk_flags_json=excluded.risk_flags_json,
                  review_status=items.review_status,
                  exclude_reason=excluded.exclude_reason
                """,
                (
                    raw.source,
                    raw.item_url,
                    raw.title,
                    raw.description,
                    raw.listed_price,
                    raw.shipping_fee,
                    raw.posted_at,
                    raw.seller_name,
                    json.dumps(raw.image_urls, ensure_ascii=False),
                    raw.fetched_at.isoformat(),
                    json.dumps(_norm_to_dict(norm), ensure_ascii=False),
                    item.expected_resale_price,
                    item.estimated_profit,
                    item.selling_fee,
                    item.shipping_cost,
                    item.risk_buffer,
                    norm.risk_score,
                    json.dumps(norm.risk_flags, ensure_ascii=False),
                    "pending",
                    item.exclude_reason,
                ),
            )

    def update_review_status(self, source: str, item_url: str, review_status: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE items
                SET review_status = ?
                WHERE source = ? AND item_url = ?
                """,
                (review_status, source, item_url),
            )
        return cur.rowcount > 0

    def list_recent_items(
        self,
        limit: int = 20,
        source: str | None = None,
        review_status: str | None = None,
    ) -> list[dict]:
        where: list[str] = []
        params: list = []
        if source:
            where.append("source = ?")
            params.append(source)
        if review_status:
            where.append("review_status = ?")
            params.append(review_status)
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        params.append(max(1, limit))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                  source, item_url, title, listed_price, estimated_profit,
                  risk_score, review_status, fetched_at, exclude_reason
                FROM items
                {where_sql}
                ORDER BY fetched_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        out = []
        for row in rows:
            out.append(
                {
                    "source": row[0],
                    "item_url": row[1],
                    "title": row[2],
                    "listed_price": row[3],
                    "estimated_profit": row[4],
                    "risk_score": row[5],
                    "review_status": row[6],
                    "fetched_at": row[7],
                    "exclude_reason": row[8],
                }
            )
        return out

    def summarize_review_status(
        self,
        source: str | None = None,
        review_status: str | None = None,
        timeseries: str = "both",
    ) -> dict:
        where: list[str] = []
        params: list = []
        if source:
            where.append("source = ?")
            params.append(source)
        if review_status:
            where.append("review_status = ?")
            params.append(review_status)
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT review_status, COUNT(*), AVG(estimated_profit)
                FROM items
                {where_sql}
                GROUP BY review_status
                """,
                params,
            ).fetchall()
            total_row = conn.execute(
                f"""
                SELECT COUNT(*), AVG(estimated_profit)
                FROM items
                {where_sql}
                """,
                params,
            ).fetchone()
            source_rows = conn.execute(
                f"""
                SELECT source, review_status, COUNT(*), AVG(estimated_profit)
                FROM items
                {where_sql}
                GROUP BY source, review_status
                """,
                params,
            ).fetchall()

            cand_params: list = []
            cand_where = ""
            if source:
                cand_where = "WHERE nh.source = ?"
                cand_params.append(source)
            candidate_rows = conn.execute(
                f"""
                SELECT i.review_status, COUNT(*)
                FROM (
                  SELECT DISTINCT source, item_url
                  FROM notification_history
                ) nh
                JOIN items i
                  ON i.source = nh.source AND i.item_url = nh.item_url
                {cand_where}
                GROUP BY i.review_status
                """,
                cand_params,
            ).fetchall()
            series_rows = conn.execute(
                f"""
                SELECT source, review_status, estimated_profit, fetched_at
                FROM items
                {where_sql}
                """,
                params,
            ).fetchall()

        counts = {"pending": 0, "watched": 0, "good": 0, "bad": 0, "bought": 0}
        avg_by_status = {"pending": None, "watched": None, "good": None, "bad": None, "bought": None}
        for status, count, avg_profit in rows:
            if status in counts:
                counts[status] = int(count)
                avg_by_status[status] = float(avg_profit) if avg_profit is not None else None

        total_items = int(total_row[0] or 0) if total_row else 0
        avg_profit_all = float(total_row[1]) if total_row and total_row[1] is not None else 0.0
        safe_div = lambda x: (x / total_items) if total_items > 0 else 0.0

        source_map: dict[str, dict] = {}
        for src, status, cnt, avg_profit in source_rows:
            if src not in source_map:
                source_map[src] = {
                    "total_items": 0,
                    "good_count": 0,
                    "bad_count": 0,
                    "bought_count": 0,
                    "good_rate": 0.0,
                    "bad_rate": 0.0,
                    "bought_rate": 0.0,
                    "average_estimated_profit": 0.0,
                    "_sum_profit": 0.0,
                }
            source_map[src]["total_items"] += int(cnt)
            source_map[src]["_sum_profit"] += float(avg_profit or 0.0) * int(cnt)
            if status == "good":
                source_map[src]["good_count"] += int(cnt)
            elif status == "bad":
                source_map[src]["bad_count"] += int(cnt)
            elif status == "bought":
                source_map[src]["bought_count"] += int(cnt)

        for src, m in source_map.items():
            t = m["total_items"]
            m["good_rate"] = (m["good_count"] / t) if t else 0.0
            m["bad_rate"] = (m["bad_count"] / t) if t else 0.0
            m["bought_rate"] = (m["bought_count"] / t) if t else 0.0
            m["average_estimated_profit"] = (m["_sum_profit"] / t) if t else 0.0
            del m["_sum_profit"]

        cand_counts = {"good": 0, "bad": 0, "bought": 0}
        candidate_total = 0
        for status, cnt in candidate_rows:
            c = int(cnt)
            candidate_total += c
            if status in cand_counts:
                cand_counts[status] += c
        cand_div = lambda x: (x / candidate_total) if candidate_total > 0 else 0.0
        daily, daily_by_source, weekly, weekly_by_source = _build_timeseries(series_rows, timeseries)

        return {
            "total_items": total_items,
            "pending_count": counts["pending"],
            "watched_count": counts["watched"],
            "good_count": counts["good"],
            "bad_count": counts["bad"],
            "bought_count": counts["bought"],
            "good_rate": safe_div(counts["good"]),
            "bad_rate": safe_div(counts["bad"]),
            "bought_rate": safe_div(counts["bought"]),
            "average_estimated_profit": avg_profit_all,
            "status_average_estimated_profit": avg_by_status,
            "source_breakdown": source_map,
            "candidate_total_items": candidate_total,
            "candidate_good_rate": cand_div(cand_counts["good"]),
            "candidate_bad_rate": cand_div(cand_counts["bad"]),
            "candidate_bought_rate": cand_div(cand_counts["bought"]),
            "timeseries_daily": daily,
            "timeseries_weekly": weekly,
            "source_timeseries_daily": daily_by_source,
            "source_timeseries_weekly": weekly_by_source,
        }

    def has_recent_notification(
        self,
        source: str,
        item_url: str,
        window_minutes: int,
        dedupe_key: str | None = None,
        similarity_key: str | None = None,
    ) -> bool:
        threshold = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
        where = "(source = ? AND item_url = ?)"
        params: list[str] = [source, item_url]
        if dedupe_key:
            where = f"{where} OR (dedupe_key = ?)"
            params.append(dedupe_key)
        if similarity_key:
            where = f"{where} OR (similarity_key = ?)"
            params.append(similarity_key)
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT COUNT(*) FROM notification_history
                WHERE ({where}) AND notified_at >= ?
                """,
                (*params, threshold.isoformat()),
            ).fetchone()
        return bool(row and row[0] > 0)

    def mark_notified(
        self,
        source: str,
        item_url: str,
        dedupe_key: str | None = None,
        similarity_key: str | None = None,
        notified_price: int | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO notification_history (source, item_url, dedupe_key, similarity_key, notified_price, notified_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (source, item_url, dedupe_key, similarity_key, notified_price, datetime.now(timezone.utc).isoformat()),
            )

    def recent_notification_context(
        self,
        source: str,
        item_url: str,
        window_minutes: int,
        dedupe_key: str | None = None,
        similarity_key: str | None = None,
    ) -> dict[str, int | bool | None]:
        threshold = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
        where = "(source = ? AND item_url = ?)"
        params: list[str] = [source, item_url]
        if dedupe_key:
            where = f"{where} OR (dedupe_key = ?)"
            params.append(dedupe_key)
        if similarity_key:
            where = f"{where} OR (similarity_key = ?)"
            params.append(similarity_key)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT item_url, notified_price
                FROM notification_history
                WHERE ({where}) AND notified_at >= ?
                ORDER BY notified_at DESC
                """,
                (*params, threshold.isoformat()),
            ).fetchall()
        same_item_recent = False
        same_item_price: int | None = None
        for row_item_url, row_notified_price in rows:
            if row_item_url == item_url:
                same_item_recent = True
                same_item_price = row_notified_price
                break
        return {
            "has_recent_duplicate": bool(rows),
            "same_item_recent": same_item_recent,
            "same_item_notified_price": same_item_price,
        }


def _build_timeseries(series_rows, mode: str):
    need_daily = mode in {"daily", "both"}
    need_weekly = mode in {"weekly", "both"}
    daily_map: dict[str, list] = {}
    weekly_map: dict[str, list] = {}
    daily_source_map: dict[str, dict[str, list]] = {}
    weekly_source_map: dict[str, dict[str, list]] = {}

    def _bucket_date(ts: str, weekly: bool) -> str:
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            return "unknown"
        if weekly:
            y, w, _ = dt.isocalendar()
            return f"{y}-W{w:02d}"
        return dt.date().isoformat()

    def _ensure(map_obj: dict, key: str):
        if key not in map_obj:
            map_obj[key] = {
                "total_items": 0,
                "good_count": 0,
                "bad_count": 0,
                "bought_count": 0,
                "good_rate": 0.0,
                "bad_rate": 0.0,
                "bought_rate": 0.0,
                "average_estimated_profit": 0.0,
                "_sum_profit": 0.0,
            }
        return map_obj[key]

    for src, status, est_profit, fetched_at in series_rows:
        if need_daily:
            d = _bucket_date(fetched_at, weekly=False)
            row = _ensure(daily_map, d)
            row["total_items"] += 1
            row["_sum_profit"] += float(est_profit or 0.0)
            srow = _ensure(daily_source_map.setdefault(src, {}), d)
            srow["total_items"] += 1
            srow["_sum_profit"] += float(est_profit or 0.0)
            _inc_status(row, status)
            _inc_status(srow, status)
        if need_weekly:
            w = _bucket_date(fetched_at, weekly=True)
            row = _ensure(weekly_map, w)
            row["total_items"] += 1
            row["_sum_profit"] += float(est_profit or 0.0)
            srow = _ensure(weekly_source_map.setdefault(src, {}), w)
            srow["total_items"] += 1
            srow["_sum_profit"] += float(est_profit or 0.0)
            _inc_status(row, status)
            _inc_status(srow, status)

    return (
        _finalize_series(daily_map),
        {k: _finalize_series(v) for k, v in daily_source_map.items()},
        _finalize_series(weekly_map),
        {k: _finalize_series(v) for k, v in weekly_source_map.items()},
    )


def _inc_status(row: dict, status: str) -> None:
    if status == "good":
        row["good_count"] += 1
    elif status == "bad":
        row["bad_count"] += 1
    elif status == "bought":
        row["bought_count"] += 1


def _finalize_series(map_obj: dict[str, dict]) -> list[dict]:
    out: list[dict] = []
    for bucket, row in sorted(map_obj.items(), key=lambda x: x[0]):
        total = row["total_items"]
        row["good_rate"] = (row["good_count"] / total) if total else 0.0
        row["bad_rate"] = (row["bad_count"] / total) if total else 0.0
        row["bought_rate"] = (row["bought_count"] / total) if total else 0.0
        row["average_estimated_profit"] = (row["_sum_profit"] / total) if total else 0.0
        del row["_sum_profit"]
        out.append({"bucket": bucket, **row})
    return out


def _norm_to_dict(norm: NormalizedFields) -> dict:
    return {
        "model_name": norm.model_name,
        "storage_gb": norm.storage_gb,
        "color": norm.color,
        "carrier": norm.carrier,
        "sim_free_flag": norm.sim_free_flag,
        "battery_health": norm.battery_health,
        "network_restriction_status": norm.network_restriction_status,
        "condition_flags": norm.condition_flags,
        "repair_history_flag": norm.repair_history_flag,
        "face_id_flag": norm.face_id_flag,
        "camera_issue_flag": norm.camera_issue_flag,
        "screen_issue_flag": norm.screen_issue_flag,
        "activation_issue_flag": norm.activation_issue_flag,
        "accessories_flags": norm.accessories_flags,
        "risk_flags": norm.risk_flags,
        "risk_score": norm.risk_score,
        "risk_score_breakdown": norm.risk_score_breakdown,
    }
