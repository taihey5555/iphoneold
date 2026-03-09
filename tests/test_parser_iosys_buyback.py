from app.parsers.iosys_buyback import IosysBuybackParser, normalize_model_name


def test_normalize_model_name_absorbs_basic_variations():
    expected = "iphone 14 pro"
    assert normalize_model_name("Apple iPhone 14 Pro") == expected
    assert normalize_model_name("iPhone 14 Pro") == expected
    assert normalize_model_name("IPHONE 14 PRO") == expected
    assert normalize_model_name("iPhone 14 Pro (128GB)") == expected
    assert normalize_model_name(" Apple　iPhone   14 Pro ") == expected
    assert normalize_model_name("apple IPHONE 14 PRO(docomo)") == expected
    assert normalize_model_name("Apple iPhone 14 Pro(SIMフリー)") == expected
    assert normalize_model_name("Apple iPhone 14 Pro 128GB docomo") == expected
    assert normalize_model_name("iPhone 14 Pro / SIMフリー / ブラック") == expected
    assert normalize_model_name("iPhone 14 Pro-256GB-SoftBank") == expected
    assert normalize_model_name("iPhone 14 Pro 1TB 国内版SIMフリー") == expected
    assert normalize_model_name("iPhone14Pro") == expected


def test_iosys_parser_maps_categories_from_header_table():
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
        <td>SIMフリー</td>
        <td>70,000円</td>
        <td>60,000円 ～ 65,000円</td>
      </tr>
    </table>
    """

    result = IosysBuybackParser().parse_quotes(
        html,
        source_url="https://iosys.example/buyback/iphone",
        quote_checked_at="2026-03-09T00:00:00+00:00",
    )

    assert result.error_count == 0
    assert len(result.rows) == 2
    assert result.rows[0].item_category == "opened_unused"
    assert result.rows[0].quoted_price_min == 70000
    assert result.rows[0].quoted_price_max == 70000
    assert result.rows[1].item_category == "used"
    assert result.rows[1].quoted_price_min == 60000
    assert result.rows[1].quoted_price_max == 65000


def test_iosys_parser_parses_current_card_style_tables():
    html = """
    <table>
      <tr>
        <td>
          docomo版SIMフリー iPhone13 128GB
          未使用品買取価格 52,000円
          中古買取価格 49,000円 ～ 39,000円
          申込みは こちら
        </td>
      </tr>
    </table>
    <table>
      <tr>
        <td>
          国内版SIMフリー iPhone 14 Pro 256GB
          未使用品買取価格 95,000円
          中古買取価格 91,000円 ～ 74,000円
          申込みは こちら
        </td>
      </tr>
    </table>
    """

    result = IosysBuybackParser().parse_quotes(
        html,
        source_url="https://k-tai-iosys.com/pricelist/smartphone/iphone/",
        quote_checked_at="2026-03-09T00:00:00+00:00",
    )

    assert result.error_count == 0
    assert len(result.rows) == 4

    first_opened = result.rows[0]
    assert first_opened.model_name_raw == "iphone13"
    assert first_opened.model_name_key == "iphone 13"
    assert first_opened.carrier_type == "docomo"
    assert first_opened.storage_gb == 128
    assert first_opened.item_category == "opened_unused"
    assert first_opened.quoted_price_min == 52000

    first_used = result.rows[1]
    assert first_used.item_category == "used"
    assert first_used.quoted_price_min == 39000
    assert first_used.quoted_price_max == 49000

    second_opened = result.rows[2]
    assert second_opened.model_name_key == "iphone 14 pro"
    assert second_opened.carrier_type == "sim_free"
    assert second_opened.storage_gb == 256


def test_iosys_parser_skips_bad_card_segment_but_keeps_valid_segment():
    html = """
    <table>
      <tr>
        <td>
          SIMフリー iPhone13 128GB 未使用品買取価格 52,000円 中古買取価格 49,000円 ～ 39,000円 申込みは こちら
          壊れたセグメント 申込みは こちら
        </td>
      </tr>
    </table>
    """

    result = IosysBuybackParser().parse_quotes(
        html,
        source_url="https://k-tai-iosys.com/pricelist/smartphone/iphone/",
        quote_checked_at="2026-03-09T00:00:00+00:00",
    )

    assert len(result.rows) == 2
    assert result.error_count == 0
