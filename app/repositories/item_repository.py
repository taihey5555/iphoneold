from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.models import NormalizedFields, RawListing, ScoredItem
from app.parsers.iosys_buyback import normalize_model_name
from app.utils.text import normalize_ws


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
                  review_note TEXT,
                  exit_channel TEXT,
                  outcome_status TEXT NOT NULL DEFAULT 'none',
                  actual_sale_price INTEGER,
                  actual_profit INTEGER,
                  outcome_note TEXT,
                  outcome_updated_at TEXT,
                  item_category TEXT,
                  exclude_reason TEXT,
                  UNIQUE(source, item_url)
                )
                """
            )
            try:
                conn.execute("ALTER TABLE items ADD COLUMN review_status TEXT NOT NULL DEFAULT 'pending'")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE items ADD COLUMN review_note TEXT")
            except sqlite3.OperationalError:
                pass
            for alter_sql in (
                "ALTER TABLE items ADD COLUMN exit_channel TEXT",
                "ALTER TABLE items ADD COLUMN outcome_status TEXT NOT NULL DEFAULT 'none'",
                "ALTER TABLE items ADD COLUMN actual_sale_price INTEGER",
                "ALTER TABLE items ADD COLUMN actual_profit INTEGER",
                "ALTER TABLE items ADD COLUMN outcome_note TEXT",
                "ALTER TABLE items ADD COLUMN outcome_updated_at TEXT",
                "ALTER TABLE items ADD COLUMN item_category TEXT",
            ):
                try:
                    conn.execute(alter_sql)
                except sqlite3.OperationalError:
                    pass
            conn.execute("CREATE INDEX IF NOT EXISTS idx_items_item_category ON items(item_category)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS notification_history (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  source TEXT NOT NULL,
                  item_url TEXT NOT NULL,
                  dedupe_key TEXT,
                  similarity_key TEXT,
                  notified_price INTEGER,
                  notification_reason TEXT,
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
            try:
                conn.execute("ALTER TABLE notification_history ADD COLUMN notification_reason TEXT")
            except sqlite3.OperationalError:
                pass
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS buyback_shops (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  shop_name TEXT NOT NULL UNIQUE,
                  accepts_sealed INTEGER NOT NULL DEFAULT 0,
                  accepts_opened_unused INTEGER NOT NULL DEFAULT 0,
                  accepts_used INTEGER NOT NULL DEFAULT 1,
                  supports_grade_pricing INTEGER NOT NULL DEFAULT 0,
                  supports_junk INTEGER NOT NULL DEFAULT 0,
                  notes TEXT,
                  is_active INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS buyback_quotes (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  source TEXT NOT NULL,
                  item_url TEXT NOT NULL,
                  shop_id INTEGER NOT NULL,
                  item_category TEXT NOT NULL,
                  quoted_price_min INTEGER NOT NULL,
                  quoted_price_max INTEGER,
                  condition_assumption TEXT,
                  quote_checked_at TEXT NOT NULL,
                  source_url TEXT,
                  notes TEXT,
                  FOREIGN KEY (shop_id) REFERENCES buyback_shops(id)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_buyback_quotes_item ON buyback_quotes(source, item_url, quote_checked_at DESC, id DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_buyback_quotes_shop ON buyback_quotes(shop_id, quote_checked_at DESC, id DESC)"
            )

    def upsert_scored_item(self, item: ScoredItem) -> None:
        raw = item.raw
        norm = item.normalized
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO items (
                  source, item_url, title, description, listed_price, shipping_fee, posted_at,
                  seller_name, image_urls_json, fetched_at, normalized_json, expected_resale_price,
                  estimated_profit, selling_fee, shipping_cost, risk_buffer, risk_score, risk_flags_json, review_status, review_note,
                  exit_channel, outcome_status, actual_sale_price, actual_profit, outcome_note, outcome_updated_at, exclude_reason
                  , item_category)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                  review_note=items.review_note,
                  exit_channel=items.exit_channel,
                  outcome_status=items.outcome_status,
                  actual_sale_price=items.actual_sale_price,
                  actual_profit=items.actual_profit,
                  outcome_note=items.outcome_note,
                  outcome_updated_at=items.outcome_updated_at,
                  item_category=items.item_category,
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
                    None,
                    None,
                    "none",
                    None,
                    None,
                    None,
                    None,
                    item.exclude_reason,
                    None,
                ),
            )

    def update_review_status(self, source: str, item_url: str, review_status: str, review_note: str | None = None) -> bool:
        with self._connect() as conn:
            if review_note is None:
                cur = conn.execute(
                    """
                    UPDATE items
                    SET review_status = ?
                    WHERE source = ? AND item_url = ?
                    """,
                    (review_status, source, item_url),
                )
            else:
                cur = conn.execute(
                    """
                    UPDATE items
                    SET review_status = ?, review_note = ?
                    WHERE source = ? AND item_url = ?
                    """,
                    (review_status, review_note, source, item_url),
                )
        return cur.rowcount > 0

    def update_item_category(self, source: str, item_url: str, item_category: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE items
                SET item_category = ?
                WHERE source = ? AND item_url = ?
                """,
                (item_category, source, item_url),
            )
        return cur.rowcount > 0

    def append_review_note(self, source: str, item_url: str, note_suffix: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT review_note
                FROM items
                WHERE source = ? AND item_url = ?
                """,
                (source, item_url),
            ).fetchone()
            if not row:
                return False
            current = row[0]
            next_note = f"{current}\n{note_suffix}" if current else note_suffix
            cur = conn.execute(
                """
                UPDATE items
                SET review_note = ?
                WHERE source = ? AND item_url = ?
                """,
                (next_note, source, item_url),
            )
        return cur.rowcount > 0

    def list_recent_items(
        self,
        limit: int = 20,
        source: str | None = None,
        review_status: str | None = None,
        missing_item_category: bool = False,
        notified_only: bool = False,
    ) -> list[dict]:
        where: list[str] = []
        params: list = []
        if source:
            where.append("source = ?")
            params.append(source)
        if review_status:
            where.append("review_status = ?")
            params.append(review_status)
        if missing_item_category:
            where.append("(item_category IS NULL OR item_category = '')")
        if notified_only:
            where.append(
                """
                EXISTS (
                  SELECT 1
                  FROM notification_history nh
                  WHERE nh.source = items.source
                    AND nh.item_url = items.item_url
                )
                """.strip()
            )
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        params.append(max(1, limit))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                  SELECT
                    source, item_url, title, description, listed_price, estimated_profit,
                    risk_score, review_status, review_note, exit_channel, outcome_status,
                    actual_sale_price, actual_profit, outcome_note, fetched_at, exclude_reason, item_category, normalized_json
                  FROM items
                  {where_sql}
                  ORDER BY fetched_at DESC
                  LIMIT ?
                """,
                params,
            ).fetchall()
        out = []
        for row in rows:
            normalized = json.loads(row[17] or "{}")
            imei_candidates = normalized.get("imei_candidates") or []
            out.append(
                {
                    "source": row[0],
                    "item_url": row[1],
                    "title": row[2],
                    "listed_price": row[4],
                    "estimated_profit": row[5],
                    "risk_score": row[6],
                    "review_status": row[7],
                    "review_note": row[8],
                    "exit_channel": row[9],
                    "outcome_status": row[10],
                    "actual_sale_price": row[11],
                    "actual_profit": row[12],
                    "outcome_note": row[13],
                    "fetched_at": row[14],
                    "exclude_reason": row[15],
                    "item_category": row[16],
                    "imei_candidates": imei_candidates,
                    "imei_count": len(imei_candidates),
                    "imei_first": imei_candidates[0] if imei_candidates else None,
                    "item_category_hint": detect_item_category_hint(row[2], row[3]),
                }
            )
        return out

    def get_item_imei_candidates(self, source: str, item_url: str) -> list[str]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT normalized_json
                FROM items
                WHERE source = ? AND item_url = ?
                """,
                (source, item_url),
            ).fetchone()
        if not row:
            return []
        normalized = json.loads(row[0] or "{}")
        return list(normalized.get("imei_candidates") or [])

    def summarize_item_category_state(self) -> dict:
        with self._connect() as conn:
            columns = [row[1] for row in conn.execute("PRAGMA table_info(items)").fetchall()]
            has_item_category = "item_category" in columns
            total = int(conn.execute("SELECT COUNT(*) FROM items").fetchone()[0])
            if not has_item_category:
                return {
                    "item_category_column_exists": False,
                    "items_total": total,
                    "item_category_missing_count": total,
                    "item_category_filled_count": 0,
                    "item_category_distribution": {"used": 0, "opened_unused": 0, "null": total},
                    "opened_unused_hint_count": 0,
                }
            distribution_rows = conn.execute(
                """
                SELECT COALESCE(NULLIF(item_category, ''), 'null') AS category, COUNT(*)
                FROM items
                GROUP BY category
                """
            ).fetchall()
            distribution = {"used": 0, "opened_unused": 0, "null": 0}
            for category, count in distribution_rows:
                if category in distribution:
                    distribution[category] = int(count)
            missing_count = distribution["null"]
            hint_rows = conn.execute(
                """
                SELECT title, description
                FROM items
                WHERE item_category IS NULL OR item_category = ''
                """
            ).fetchall()
        opened_unused_hint_count = sum(
            1 for title, description in hint_rows if detect_item_category_hint(title, description) == "opened_unused"
        )
        return {
            "item_category_column_exists": True,
            "items_total": total,
            "item_category_missing_count": missing_count,
            "item_category_filled_count": total - missing_count,
            "item_category_distribution": distribution,
            "opened_unused_hint_count": opened_unused_hint_count,
        }

    def add_buyback_shop(
        self,
        shop_name: str,
        accepts_sealed: bool = False,
        accepts_opened_unused: bool = False,
        accepts_used: bool = True,
        supports_grade_pricing: bool = False,
        supports_junk: bool = False,
        notes: str | None = None,
        is_active: bool = True,
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO buyback_shops (
                  shop_name, accepts_sealed, accepts_opened_unused, accepts_used,
                  supports_grade_pricing, supports_junk, notes, is_active
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    shop_name,
                    _bool_to_int(accepts_sealed),
                    _bool_to_int(accepts_opened_unused),
                    _bool_to_int(accepts_used),
                    _bool_to_int(supports_grade_pricing),
                    _bool_to_int(supports_junk),
                    notes,
                    _bool_to_int(is_active),
                ),
            )
        return int(cur.lastrowid)

    def update_buyback_shop(self, shop_id: int, **fields) -> bool:
        if not fields:
            return False
        allowed = {
            "shop_name",
            "accepts_sealed",
            "accepts_opened_unused",
            "accepts_used",
            "supports_grade_pricing",
            "supports_junk",
            "notes",
            "is_active",
        }
        sets: list[str] = []
        params: list = []
        for key, value in fields.items():
            if key not in allowed:
                continue
            if key.startswith("accepts_") or key.startswith("supports_") or key == "is_active":
                value = _bool_to_int(bool(value))
            sets.append(f"{key} = ?")
            params.append(value)
        if not sets:
            return False
        params.append(shop_id)
        with self._connect() as conn:
            cur = conn.execute(
                f"""
                UPDATE buyback_shops
                SET {", ".join(sets)}
                WHERE id = ?
                """,
                params,
            )
        return cur.rowcount > 0

    def list_buyback_shops(self, active_only: bool = False) -> list[dict]:
        where_sql = "WHERE is_active = 1" if active_only else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                  id, shop_name, accepts_sealed, accepts_opened_unused, accepts_used,
                  supports_grade_pricing, supports_junk, notes, is_active
                FROM buyback_shops
                {where_sql}
                ORDER BY is_active DESC, shop_name ASC, id ASC
                """
            ).fetchall()
        return [_row_to_buyback_shop_dict(row) for row in rows]

    def resolve_buyback_shop_id(self, shop_name_or_id: str) -> int | None:
        lookup_id = _coerce_int(shop_name_or_id)
        with self._connect() as conn:
            if lookup_id is not None:
                row = conn.execute("SELECT id FROM buyback_shops WHERE id = ?", (lookup_id,)).fetchone()
                if row:
                    return int(row[0])
            row = conn.execute(
                "SELECT id FROM buyback_shops WHERE shop_name = ? COLLATE NOCASE",
                (shop_name_or_id,),
            ).fetchone()
        return int(row[0]) if row else None

    def insert_buyback_quote(
        self,
        source: str,
        item_url: str,
        shop_id: int,
        item_category: str,
        quoted_price_min: int,
        quoted_price_max: int | None = None,
        condition_assumption: str | None = None,
        source_url: str | None = None,
        notes: str | None = None,
        quote_checked_at: str | None = None,
    ) -> int:
        checked_at = quote_checked_at or datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO buyback_quotes (
                  source, item_url, shop_id, item_category, quoted_price_min, quoted_price_max,
                  condition_assumption, quote_checked_at, source_url, notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source,
                    item_url,
                    shop_id,
                    item_category,
                    quoted_price_min,
                    quoted_price_max,
                    condition_assumption,
                    checked_at,
                    source_url,
                    notes,
                ),
            )
        return int(cur.lastrowid)

    def list_buyback_quotes(self, source: str, item_url: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                  q.id,
                  q.source,
                  q.item_url,
                  q.shop_id,
                  s.shop_name,
                  q.item_category,
                  q.quoted_price_min,
                  q.quoted_price_max,
                  q.condition_assumption,
                  q.quote_checked_at,
                  q.source_url,
                  q.notes,
                  s.is_active
                FROM buyback_quotes q
                JOIN buyback_shops s ON s.id = q.shop_id
                WHERE q.source = ? AND q.item_url = ?
                ORDER BY q.quote_checked_at DESC, q.id DESC
                """,
                (source, item_url),
            ).fetchall()
        out: list[dict] = []
        for row in rows:
            out.append(
                {
                    "id": row[0],
                    "source": row[1],
                    "item_url": row[2],
                    "shop_id": row[3],
                    "shop_name": row[4],
                    "item_category": row[5],
                    "quoted_price_min": row[6],
                    "quoted_price_max": row[7],
                    "condition_assumption": row[8],
                    "quote_checked_at": row[9],
                    "source_url": row[10],
                    "notes": row[11],
                    "shop_is_active": bool(row[12]),
                }
            )
        return out

    def list_latest_buyback_quotes_by_shop(self, source: str, item_url: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                  q.id,
                  q.source,
                  q.item_url,
                  q.shop_id,
                  s.shop_name,
                  q.item_category,
                  q.quoted_price_min,
                  q.quoted_price_max,
                  q.condition_assumption,
                  q.quote_checked_at,
                  q.source_url,
                  q.notes,
                  s.accepts_sealed,
                  s.accepts_opened_unused,
                  s.accepts_used,
                  s.supports_grade_pricing,
                  s.supports_junk,
                  s.is_active
                FROM buyback_quotes q
                JOIN buyback_shops s ON s.id = q.shop_id
                WHERE q.source = ? AND q.item_url = ?
                  AND q.id = (
                    SELECT q2.id
                    FROM buyback_quotes q2
                    WHERE q2.source = q.source
                      AND q2.item_url = q.item_url
                      AND q2.shop_id = q.shop_id
                    ORDER BY q2.quote_checked_at DESC, q2.id DESC
                    LIMIT 1
                  )
                ORDER BY q.shop_id ASC
                """,
                (source, item_url),
            ).fetchall()
        out: list[dict] = []
        for row in rows:
            out.append(
                {
                    "id": row[0],
                    "source": row[1],
                    "item_url": row[2],
                    "shop_id": row[3],
                    "shop_name": row[4],
                    "item_category": row[5],
                    "quoted_price_min": row[6],
                    "quoted_price_max": row[7],
                    "condition_assumption": row[8],
                    "quote_checked_at": row[9],
                    "source_url": row[10],
                    "notes": row[11],
                    "accepts_sealed": bool(row[12]),
                    "accepts_opened_unused": bool(row[13]),
                    "accepts_used": bool(row[14]),
                    "supports_grade_pricing": bool(row[15]),
                    "supports_junk": bool(row[16]),
                    "shop_is_active": bool(row[17]),
                }
            )
        return out

    def get_latest_buyback_quote_for_item_shop(self, source: str, item_url: str, shop_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                  q.id,
                  q.item_category,
                  q.quoted_price_min,
                  q.quoted_price_max,
                  q.condition_assumption,
                  q.quote_checked_at,
                  q.source_url,
                  q.notes
                FROM buyback_quotes q
                WHERE q.source = ? AND q.item_url = ? AND q.shop_id = ?
                ORDER BY q.quote_checked_at DESC, q.id DESC
                LIMIT 1
                """,
                (source, item_url, shop_id),
            ).fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "item_category": row[1],
            "quoted_price_min": row[2],
            "quoted_price_max": row[3],
            "condition_assumption": row[4],
            "quote_checked_at": row[5],
            "source_url": row[6],
            "notes": row[7],
        }

    def find_iosys_buyback_candidates(self, carrier_type: str, storage_gb: int) -> list[dict]:
        where = [
            "CAST(json_extract(normalized_json, '$.storage_gb') AS INTEGER) = ?",
        ]
        params: list[object] = [int(storage_gb)]
        if carrier_type == "sim_free":
            where.append("CAST(json_extract(normalized_json, '$.sim_free_flag') AS INTEGER) = 1")
        else:
            where.append("LOWER(COALESCE(json_extract(normalized_json, '$.carrier'), '')) = ?")
            params.append(str(carrier_type).lower())
        where_sql = " AND ".join(where)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT source, item_url, normalized_json, item_category
                FROM items
                WHERE {where_sql}
                """,
                params,
            ).fetchall()
        out: list[dict] = []
        for row in rows:
            normalized = json.loads(row[2] or "{}")
            out.append(
                {
                    "source": row[0],
                    "item_url": row[1],
                    "normalized": normalized,
                    "item_category": row[3],
                }
            )
        return out

    def find_iosys_buyback_candidates_for_storage(self, storage_gb: int) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT source, item_url, normalized_json, item_category
                FROM items
                WHERE CAST(json_extract(normalized_json, '$.storage_gb') AS INTEGER) = ?
                """,
                (int(storage_gb),),
            ).fetchall()
        out: list[dict] = []
        for row in rows:
            out.append(
                {
                    "source": row[0],
                    "item_url": row[1],
                    "normalized": json.loads(row[2] or "{}"),
                    "item_category": row[3],
                }
            )
        return out

    def find_items_for_iosys_buyback(
        self,
        model_name_key: str,
        carrier_type: str,
        storage_gb: int,
        item_category: str,
    ) -> list[dict]:
        candidates = self.find_iosys_buyback_candidates(carrier_type=carrier_type, storage_gb=storage_gb)
        out: list[dict] = []
        for row in candidates:
            current_model_key = normalize_model_name(row["normalized"].get("model_name") or "")
            if current_model_key != model_name_key:
                continue
            if row.get("item_category") != item_category:
                continue
            out.append(row)
        return out

    def get_item_buyback_context(self, source: str, item_url: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                  source, item_url, title, listed_price, shipping_fee, estimated_profit,
                  selling_fee, risk_score, risk_flags_json, item_category, review_status, outcome_status,
                  review_note, exit_channel, actual_sale_price, actual_profit
                FROM items
                WHERE source = ? AND item_url = ?
                """,
                (source, item_url),
            ).fetchone()
        if not row:
            return None
        return {
            "source": row[0],
            "item_url": row[1],
            "title": row[2],
            "listed_price": row[3],
            "shipping_fee": row[4],
            "estimated_profit": row[5],
            "selling_fee": row[6],
            "risk_score": row[7],
            "risk_flags": json.loads(row[8] or "[]"),
            "item_category": row[9],
            "review_status": row[10],
            "outcome_status": row[11],
            "review_note": row[12],
            "exit_channel": row[13],
            "actual_sale_price": row[14],
            "actual_profit": row[15],
        }

    def update_outcome(
        self,
        source: str,
        item_url: str,
        outcome_status: str,
        exit_channel: str | None = None,
        actual_sale_price: int | None = None,
        outcome_note: str | None = None,
    ) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT listed_price, shipping_fee
                FROM items
                WHERE source = ? AND item_url = ?
                """,
                (source, item_url),
            ).fetchone()
            if not row:
                return False
            purchase_price = int(row[0] or 0) + int(row[1] or 0)
            actual_profit = _compute_actual_profit(
                purchase_price=purchase_price,
                exit_channel=exit_channel,
                actual_sale_price=actual_sale_price,
            )
            cur = conn.execute(
                """
                UPDATE items
                SET exit_channel = ?,
                    outcome_status = ?,
                    actual_sale_price = ?,
                    actual_profit = ?,
                    outcome_note = ?,
                    outcome_updated_at = ?
                WHERE source = ? AND item_url = ?
                """,
                (
                    exit_channel,
                    outcome_status,
                    actual_sale_price,
                    actual_profit,
                    outcome_note,
                    datetime.now(timezone.utc).isoformat(),
                    source,
                    item_url,
                ),
            )
        return cur.rowcount > 0

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

    def summarize_outcomes(
        self,
        source: str | None = None,
        exit_channel: str | None = None,
    ) -> dict:
        where = ["outcome_status != 'none'"]
        params: list = []
        if source:
            where.append("source = ?")
            params.append(source)
        if exit_channel:
            where.append("exit_channel = ?")
            params.append(exit_channel)
        where_sql = f"WHERE {' AND '.join(where)}"
        with self._connect() as conn:
            total_row = conn.execute(
                f"""
                SELECT COUNT(*), AVG(actual_profit)
                FROM items
                {where_sql}
                """,
                params,
            ).fetchone()
            status_rows = conn.execute(
                f"""
                SELECT outcome_status, COUNT(*), AVG(actual_profit)
                FROM items
                {where_sql}
                GROUP BY outcome_status
                """,
                params,
            ).fetchall()
            channel_rows = conn.execute(
                f"""
                SELECT exit_channel, COUNT(*), AVG(actual_profit), SUM(CASE WHEN actual_profit > 0 THEN 1 ELSE 0 END)
                FROM items
                {where_sql}
                GROUP BY exit_channel
                """,
                params,
            ).fetchall()
            realized_row = conn.execute(
                f"""
                SELECT COUNT(*), AVG(actual_profit), SUM(actual_profit)
                FROM items
                {where_sql} AND actual_profit IS NOT NULL
                """,
                params,
            ).fetchone()

        total_items = int(total_row[0] or 0) if total_row else 0
        avg_actual_profit = float(total_row[1]) if total_row and total_row[1] is not None else 0.0
        realized_count = int(realized_row[0] or 0) if realized_row else 0
        realized_avg = float(realized_row[1]) if realized_row and realized_row[1] is not None else 0.0
        realized_sum = int(realized_row[2] or 0) if realized_row and realized_row[2] is not None else 0

        status_map: dict[str, dict] = {}
        for status, count, avg_profit in status_rows:
            status_map[status] = {
                "count": int(count),
                "average_actual_profit": float(avg_profit) if avg_profit is not None else None,
            }

        channel_map: dict[str, dict] = {}
        for channel, count, avg_profit, profitable_count in channel_rows:
            key = channel or "unknown"
            total = int(count)
            profitable = int(profitable_count or 0)
            channel_map[key] = {
                "count": total,
                "average_actual_profit": float(avg_profit) if avg_profit is not None else None,
                "profitable_count": profitable,
                "profitable_rate": (profitable / total) if total else 0.0,
            }

        safe_div = lambda x: (x / total_items) if total_items > 0 else 0.0
        return {
            "total_items": total_items,
            "average_actual_profit": avg_actual_profit,
            "realized_count": realized_count,
            "realized_average_actual_profit": realized_avg,
            "realized_total_profit": realized_sum,
            "bought_count": status_map.get("bought", {}).get("count", 0),
            "sold_count": status_map.get("sold", {}).get("count", 0),
            "buyback_done_count": status_map.get("buyback_done", {}).get("count", 0),
            "passed_count": status_map.get("passed", {}).get("count", 0),
            "loss_count": status_map.get("loss", {}).get("count", 0),
            "sold_rate": safe_div(status_map.get("sold", {}).get("count", 0)),
            "buyback_done_rate": safe_div(status_map.get("buyback_done", {}).get("count", 0)),
            "loss_rate": safe_div(status_map.get("loss", {}).get("count", 0)),
            "status_breakdown": status_map,
            "channel_breakdown": channel_map,
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
        notification_reason: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO notification_history (source, item_url, dedupe_key, similarity_key, notified_price, notification_reason, notified_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source,
                    item_url,
                    dedupe_key,
                    similarity_key,
                    notified_price,
                    notification_reason,
                    datetime.now(timezone.utc).isoformat(),
                ),
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

    def list_daily_note_items(self, target_date: str, source: str | None = None) -> list[dict]:
        params: list = [target_date]
        source_sql = ""
        if source:
            source_sql = "AND nh.source = ?"
            params.append(source)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                  i.source,
                  i.item_url,
                  i.title,
                  i.listed_price,
                  i.estimated_profit,
                  i.review_status,
                  i.review_note,
                  i.exit_channel,
                  i.outcome_status,
                  i.actual_sale_price,
                  i.actual_profit,
                  i.outcome_note,
                  nh.notification_reason,
                  nh.notified_at
                FROM (
                  SELECT item_url, source, MAX(notified_at) AS latest_notified_at
                  FROM notification_history
                  WHERE substr(notified_at, 1, 10) = ?
                  {source_sql}
                  GROUP BY source, item_url
                ) latest
                JOIN notification_history nh
                  ON nh.source = latest.source
                 AND nh.item_url = latest.item_url
                 AND nh.notified_at = latest.latest_notified_at
                JOIN items i
                  ON i.source = nh.source AND i.item_url = nh.item_url
                ORDER BY nh.notified_at ASC, i.item_url ASC
                """,
                params,
            ).fetchall()
        out: list[dict] = []
        for row in rows:
            out.append(
                {
                    "source": row[0],
                    "item_url": row[1],
                    "title": row[2],
                    "listed_price": row[3],
                    "estimated_profit": row[4],
                    "review_status": row[5],
                    "review_note": row[6],
                    "exit_channel": row[7],
                    "outcome_status": row[8],
                    "actual_sale_price": row[9],
                    "actual_profit": row[10],
                    "outcome_note": row[11],
                    "notification_reason": row[12],
                    "notified_at": row[13],
                }
            )
        return out


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
        "imei_candidates": norm.imei_candidates,
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


def detect_item_category_hint(title: str | None, description: str | None) -> str | None:
    text = normalize_ws(f"{title or ''} {description or ''}").lower()
    if any(word in text for word in ("開封済み未使用", "未使用", "動作確認のみ")):
        return "opened_unused"
    return None


def _compute_actual_profit(
    purchase_price: int,
    exit_channel: str | None,
    actual_sale_price: int | None,
) -> int | None:
    if actual_sale_price is None:
        return None
    if exit_channel == "mercari_resale":
        selling_fee = int(actual_sale_price * 0.1)
        shipping_cost = 750
        return actual_sale_price - purchase_price - selling_fee - shipping_cost
    if exit_channel == "buyback_shop":
        return actual_sale_price - purchase_price
    return actual_sale_price - purchase_price


def _bool_to_int(value: bool) -> int:
    return 1 if value else 0


def _coerce_int(value) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _row_to_buyback_shop_dict(row) -> dict:
    return {
        "id": row[0],
        "shop_name": row[1],
        "accepts_sealed": bool(row[2]),
        "accepts_opened_unused": bool(row[3]),
        "accepts_used": bool(row[4]),
        "supports_grade_pricing": bool(row[5]),
        "supports_junk": bool(row[6]),
        "notes": row[7],
        "is_active": bool(row[8]),
    }
