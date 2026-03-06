from app.parsers.mercari_public import MercariPublicParser


def test_mercari_url_policy():
    parser = MercariPublicParser()
    assert parser.is_allowed_listing_url("https://jp.mercari.com/search?keyword=iphone")
    assert parser.is_allowed_item_url("https://jp.mercari.com/item/m123456789")
    assert not parser.is_allowed_item_url("https://jp.mercari.com/v1/items")
    assert not parser.is_allowed_item_url("https://jp.mercari.com/purchase/m123")


def test_mercari_parse_listing_public_links():
    parser = MercariPublicParser()
    html = """
    <a href="/item/m111">iPhone 14 128GB ¥59,800</a>
    <a href="/item/m222">iPhone 15 128GB ¥88,000</a>
    """
    out = parser.parse_listing(html)
    assert len(out) == 2
    assert out[0].url == "https://jp.mercari.com/item/m111"
    assert out[0].listed_price == 59800


def test_mercari_parse_item_uses_meta_jsonld():
    parser = MercariPublicParser()
    html = """
    <html>
      <head>
        <meta property="og:title" content="iPhone 13 128GB">
        <meta name="description" content="SIMフリー 美品">
        <meta property="product:price:amount" content="49999">
        <script type="application/ld+json">
          {"@type":"Product","image":["https://img/1.jpg"]}
        </script>
      </head>
      <body><time datetime="2026-03-06T12:00:00+09:00"></time></body>
    </html>
    """
    item = parser.parse_item("mercari_public", "https://jp.mercari.com/item/m111", html)
    assert item.title == "iPhone 13 128GB"
    assert item.description == "SIMフリー 美品"
    assert item.listed_price == 49999
    assert item.image_urls == ["https://img/1.jpg"]
