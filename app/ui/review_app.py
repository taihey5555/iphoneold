from __future__ import annotations

from html import escape
from io import BytesIO
from urllib.parse import parse_qs, urlencode
from wsgiref.simple_server import make_server

from app.repositories.item_repository import ItemRepository


class ReviewUIApp:
    def __init__(self, repository: ItemRepository) -> None:
        self.repository = repository

    def __call__(self, environ, start_response):
        method = environ.get("REQUEST_METHOD", "GET").upper()
        path = environ.get("PATH_INFO", "/")
        if method == "GET" and path == "/":
            return self._handle_index(environ, start_response)
        if method == "POST" and path == "/item-category":
            return self._handle_item_category(environ, start_response)
        if method == "POST" and path == "/review-status":
            return self._handle_review_status(environ, start_response)
        start_response("404 Not Found", [("Content-Type", "text/plain; charset=utf-8")])
        return [b"not found"]

    def _handle_index(self, environ, start_response):
        params = parse_qs(environ.get("QUERY_STRING", ""), keep_blank_values=True)
        missing_only = params.get("missing_only", ["1"])[0] == "1"
        status_focus = params.get("status_focus", ["0"])[0] == "1"
        hint_first = params.get("hint_first", ["1"])[0] == "1"
        notified_only = params.get("notified_only", ["1"])[0] == "1"
        limit = _parse_limit(params.get("limit", ["20"])[0])
        rows = self.repository.list_recent_items(
            limit=max(limit, 200),
            missing_item_category=missing_only,
            notified_only=notified_only,
        )
        if status_focus:
            rows = [row for row in rows if row.get("review_status") in {"good", "watched"}]
        if hint_first:
            rows = sorted(
                rows,
                key=lambda row: (
                    0 if row.get("item_category_hint") == "opened_unused" else 1,
                    0 if row.get("review_status") in {"good", "watched"} else 1,
                    str(row.get("fetched_at") or ""),
                ),
                reverse=False,
            )
        rows = rows[:limit]
        body = _render_index(
            rows,
            missing_only=missing_only,
            status_focus=status_focus,
            hint_first=hint_first,
            notified_only=notified_only,
            limit=limit,
        )
        start_response("200 OK", [("Content-Type", "text/html; charset=utf-8")])
        return [body.encode("utf-8")]

    def _handle_item_category(self, environ, start_response):
        form = _read_form(environ)
        self.repository.update_item_category(form["source"], form["item_url"], form["item_category"])
        return self._redirect(start_response, self._redirect_target(environ))

    def _handle_review_status(self, environ, start_response):
        form = _read_form(environ)
        self.repository.update_review_status(form["source"], form["item_url"], form["review_status"])
        return self._redirect(start_response, self._redirect_target(environ))

    def _redirect(self, start_response, location: str):
        start_response("302 Found", [("Location", location)])
        return [b""]

    def _redirect_target(self, environ) -> str:
        query = environ.get("QUERY_STRING", "")
        return f"/?{query}" if query else "/"


def run_review_ui(repository: ItemRepository, host: str, port: int) -> None:
    app = ReviewUIApp(repository)
    with make_server(host, port, app) as httpd:
        print(f"review ui listening: http://{host}:{port}/")
        httpd.serve_forever()


def _read_form(environ) -> dict[str, str]:
    length = int(environ.get("CONTENT_LENGTH") or "0")
    raw = environ["wsgi.input"].read(length) if length > 0 else b""
    parsed = parse_qs(raw.decode("utf-8"), keep_blank_values=True)
    return {key: values[0] for key, values in parsed.items()}


def _render_index(rows: list[dict], *, missing_only: bool, status_focus: bool, hint_first: bool, notified_only: bool, limit: int) -> str:
    controls = _render_controls(
        missing_only=missing_only,
        status_focus=status_focus,
        hint_first=hint_first,
        notified_only=notified_only,
        limit=limit,
    )
    cards = "\n".join(
        _render_card(
            row,
            missing_only=missing_only,
            status_focus=status_focus,
            hint_first=hint_first,
            notified_only=notified_only,
            limit=limit,
        )
        for row in rows
    )
    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Item Category Review</title>
  <style>
    body {{ font-family: sans-serif; margin: 24px; }}
    .toolbar form {{ display: flex; gap: 12px; flex-wrap: wrap; align-items: center; margin-bottom: 16px; }}
    .card {{ border: 1px solid #ccc; padding: 12px; margin-bottom: 10px; }}
    .meta {{ font-size: 14px; margin: 4px 0; }}
    .hint {{ font-weight: 700; }}
    .actions {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }}
    button {{ padding: 4px 8px; cursor: pointer; }}
    a {{ color: #0b5cab; }}
  </style>
</head>
<body>
  <h1>Item Category Review</h1>
  {controls}
  <p>{len(rows)} items</p>
  {cards or "<p>no items</p>"}
</body>
</html>"""


def _render_controls(*, missing_only: bool, status_focus: bool, hint_first: bool, notified_only: bool, limit: int) -> str:
    return f"""
<form method="get" action="/">
  <label><input type="checkbox" name="notified_only" value="1" {'checked' if notified_only else ''}> notified only</label>
  <label><input type="checkbox" name="missing_only" value="1" {'checked' if missing_only else ''}> missing item_category only</label>
  <label><input type="checkbox" name="status_focus" value="1" {'checked' if status_focus else ''}> good / watched only</label>
  <label><input type="checkbox" name="hint_first" value="1" {'checked' if hint_first else ''}> hint=opened_unused first</label>
  <label>limit <input type="number" name="limit" value="{limit}" min="1" max="200" style="width:72px"></label>
  <button type="submit">Refresh</button>
</form>"""


def _render_card(row: dict, *, missing_only: bool, status_focus: bool, hint_first: bool, notified_only: bool, limit: int) -> str:
    query = _build_query(
        missing_only=missing_only,
        status_focus=status_focus,
        hint_first=hint_first,
        notified_only=notified_only,
        limit=limit,
    )
    source = escape(str(row["source"]))
    item_url = escape(str(row["item_url"]))
    title = escape(str(row["title"]))
    hint = escape(str(row.get("item_category_hint") or "-"))
    item_category = escape(str(row.get("item_category") or "-"))
    review_status = escape(str(row.get("review_status") or "-"))
    review_note = escape(str(row.get("review_note") or ""))
    meta = (
        f"price={row['listed_price']} profit={row['estimated_profit']} "
        f"risk={row['risk_score']} fetched_at={escape(str(row['fetched_at']))}"
    )
    return f"""
<div class="card">
  <div><strong>{title}</strong></div>
  <div class="meta">status={review_status} | current_category={item_category} | <span class="hint">hint={hint}</span></div>
  <div class="meta">{meta}</div>
  <div><a href="{item_url}" target="_blank" rel="noreferrer">Open item URL</a></div>
  {f'<div class="meta">note={review_note}</div>' if review_note else ''}
  <div class="actions">
    {_post_button('/item-category', source, item_url, query, 'item_category', 'used', 'used')}
    {_post_button('/item-category', source, item_url, query, 'item_category', 'opened_unused', 'opened_unused')}
    <a href="/?{query}">skip</a>
    {_post_button('/review-status', source, item_url, query, 'review_status', 'good', 'good')}
    {_post_button('/review-status', source, item_url, query, 'review_status', 'watched', 'watched')}
    {_post_button('/review-status', source, item_url, query, 'review_status', 'bad', 'bad')}
  </div>
</div>"""


def _post_button(action: str, source: str, item_url: str, query: str, field_name: str, field_value: str, label: str) -> str:
    hidden = [
        f'<input type="hidden" name="source" value="{source}">',
        f'<input type="hidden" name="item_url" value="{item_url}">',
    ]
    if field_name:
        hidden.append(f'<input type="hidden" name="{field_name}" value="{field_value}">')
    return (
        f'<form method="post" action="{action}?{query}">'
        + "".join(hidden)
        + f'<button type="submit">{escape(label)}</button></form>'
    )


def _build_query(*, missing_only: bool, status_focus: bool, hint_first: bool, notified_only: bool, limit: int) -> str:
    return urlencode(
        {
            "notified_only": "1" if notified_only else "0",
            "missing_only": "1" if missing_only else "0",
            "status_focus": "1" if status_focus else "0",
            "hint_first": "1" if hint_first else "0",
            "limit": str(limit),
        }
    )


def _parse_limit(raw: str) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 20
    return min(max(value, 1), 200)
