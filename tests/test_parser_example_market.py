from app.parsers.example_market import ExampleMarketParser


def test_parse_listing_minimal():
    parser = ExampleMarketParser(base_url="https://example.com")
    html = """
    <div class="item-card">
      <a class="item-link" href="/item/1">iPhone 14 128GB</a>
      <div class="item-price">59,800円</div>
      <div class="item-posted-at">2026-03-01</div>
    </div>
    """
    out = parser.parse_listing(html)
    assert len(out) == 1
    assert out[0].url == "https://example.com/item/1"
    assert out[0].listed_price == 59800


def test_parse_listing_with_alt_selectors():
    parser = ExampleMarketParser(base_url="https://example.com")
    html = """
    <article>
      <a href="/item/2">iPhone 13 128GB</a>
      <span class="price">49,800円</span>
      <time datetime="2026-03-02">2026/03/02</time>
    </article>
    """
    out = parser.parse_listing(html)
    assert len(out) == 1
    assert out[0].url == "https://example.com/item/2"
    assert out[0].listed_price == 49800


def test_parse_item_with_json_ld_fallback():
    parser = ExampleMarketParser(base_url="https://example.com")
    html = """
    <html>
      <head>
        <meta property="og:title" content="iPhone 15 128GB">
        <script type="application/ld+json">
          {"@type":"Product","offers":{"price":"88000"},"image":["https://img/1.jpg"]}
        </script>
      </head>
      <body>
        <meta name="description" content="状態良好">
      </body>
    </html>
    """
    item = parser.parse_item("example_market", "https://example.com/item/3", html)
    assert item.title == "iPhone 15 128GB"
    assert item.listed_price == 88000
    assert item.description == "状態良好"
    assert item.image_urls == ["https://img/1.jpg"]
