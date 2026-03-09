from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO

from app.models import CandidateItem, NormalizedFields, RawListing
from app.repositories.item_repository import ItemRepository
from app.scoring import ProfitEstimator
from app.ui.review_app import ReviewUIApp


def _insert_item(db_path, item_url: str, *, description: str = "", review_status: str = "pending"):
    repo = ItemRepository(str(db_path))
    raw = RawListing(
        source="mercari_public",
        item_url=item_url,
        title="iPhone 14 128GB",
        description=description,
        listed_price=50000,
        shipping_fee=0,
        posted_at=None,
        seller_name="seller",
        image_urls=[],
        fetched_at=datetime.now(timezone.utc),
    )
    imei_candidates = ["356789012345678"] if "IMEI" in description else []
    item = CandidateItem(
        raw=raw,
        normalized=NormalizedFields(model_name="iPhone 14", storage_gb=128, imei_candidates=imei_candidates),
        exclude_reason=None,
    )
    repo.upsert_scored_item(ProfitEstimator([]).score(item))
    repo.update_review_status("mercari_public", item_url, review_status)
    return repo


def _call_app(app, method: str, path: str, query: str = "", body: str = ""):
    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = headers

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "CONTENT_LENGTH": str(len(body.encode("utf-8"))),
        "wsgi.input": BytesIO(body.encode("utf-8")),
    }
    chunks = app(environ, start_response)
    captured["body"] = b"".join(chunks).decode("utf-8")
    return captured


def test_review_ui_index_and_filter_persistence(tmp_path):
    db_path = tmp_path / "test.db"
    repo = _insert_item(db_path, "https://jp.mercari.com/item/u1", description="開封済み未使用", review_status="watched")
    repo.mark_notified("mercari_public", "https://jp.mercari.com/item/u1")
    app = ReviewUIApp(repo)

    response = _call_app(app, "GET", "/", "notified_only=1&missing_only=1&status_focus=1&hint_first=1&limit=20")
    assert response["status"].startswith("200")
    assert "hint=opened_unused" in response["body"]
    assert 'name="limit" value="20"' in response["body"]
    assert 'name="notified_only" value="1" checked' in response["body"]
    assert "Open item URL" in response["body"]


def test_review_ui_post_updates_and_redirects_with_filters(tmp_path):
    db_path = tmp_path / "test.db"
    repo = _insert_item(db_path, "https://jp.mercari.com/item/u2", description="開封済み未使用")
    repo.mark_notified("mercari_public", "https://jp.mercari.com/item/u2")
    app = ReviewUIApp(repo)

    response = _call_app(
        app,
        "POST",
        "/item-category",
        "notified_only=1&missing_only=1&status_focus=0&hint_first=1&limit=50",
        "source=mercari_public&item_url=https%3A%2F%2Fjp.mercari.com%2Fitem%2Fu2&item_category=opened_unused",
    )
    assert response["status"].startswith("302")
    headers = dict(response["headers"])
    assert headers["Location"] == "/?notified_only=1&missing_only=1&status_focus=0&hint_first=1&limit=50"
    rows = repo.list_recent_items(limit=10, missing_item_category=False)
    assert rows[0]["item_category"] == "opened_unused"

    response = _call_app(
        app,
        "POST",
        "/review-status",
        "notified_only=1&missing_only=1&status_focus=0&hint_first=1&limit=50",
        "source=mercari_public&item_url=https%3A%2F%2Fjp.mercari.com%2Fitem%2Fu2&review_status=good",
    )
    assert response["status"].startswith("302")
    rows = repo.list_recent_items(limit=10, missing_item_category=False)
    assert rows[0]["review_status"] == "good"


def test_review_ui_notified_only_hides_unnotified_items(tmp_path):
    db_path = tmp_path / "test.db"
    repo = _insert_item(db_path, "https://jp.mercari.com/item/u3", description="開封済み未使用", review_status="watched")
    _insert_item(db_path, "https://jp.mercari.com/item/u4", description="開封済み未使用", review_status="watched")
    repo.mark_notified("mercari_public", "https://jp.mercari.com/item/u3")
    app = ReviewUIApp(repo)

    response = _call_app(app, "GET", "/", "notified_only=1&missing_only=1&status_focus=1&hint_first=1&limit=20")
    assert "https://jp.mercari.com/item/u3" in response["body"]
    assert "https://jp.mercari.com/item/u4" not in response["body"]


def test_review_ui_shows_imei_and_checker_link(tmp_path):
    db_path = tmp_path / "test.db"
    repo = _insert_item(db_path, "https://jp.mercari.com/item/u5", description="IMEI 356789012345678", review_status="watched")
    repo.mark_notified("mercari_public", "https://jp.mercari.com/item/u5")
    app = ReviewUIApp(repo)

    response = _call_app(app, "GET", "/", "notified_only=1&missing_only=0&status_focus=0&hint_first=0&limit=20")
    assert "IMEI=356789012345678" in response["body"]
    assert "https://naoseru.com/ja/imei-checker/" in response["body"]
