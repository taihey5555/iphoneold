# 中古スマホ監視bot (MVP)

規約順守前提で中古スマホ出品を監視し、条件抽出・粗利推定・危険フラグ付け・Telegram通知を行う Python CLI です。  
自動購入、購入制限回避、CAPTCHA回避、ログイン突破、保護回避は実装していません。

## 設計方針 (簡潔)
- 取得層は `ScraplingFetcher` に閉じ込め、アプリ本体を Scrapling 非依存化
- parser 層をサイト別分離 (`app/parsers/`)
- ルールベース抽出を先に実装し、LLM抽出は interface 化で後付け可能
- SQLite 保存 + 重複通知防止
- 通知条件を満たしたものだけ Telegram 通知

## 初回実URL対象範囲
- 対象: メルカリの公開検索ページ (`https://jp.mercari.com/search?...`)
- 対象: メルカリの公開商品ページ (`https://jp.mercari.com/item/m...`)
- 目標: 「一覧1ページ取得 -> 商品詳細数件取得 -> 正規化 -> SQLite保存」

## 除外範囲
- ログイン後ページ
- 購入ページ
- 売却ページ
- 取引ページ
- 内部APIエンドポイント（`/v1`, `/v2` 等）

上記除外範囲は `mercari_public` parser のURL許可判定でスキップします。

## ディレクトリ
```text
.
 app/
   main.py
   config.py
   models/
   services/
   parsers/
   repositories/
   scoring/
   notifiers/
   extractors/
   utils/
   cli/
 tests/
 scripts/
 data/
 docs/
 .env.example
 config.example.yaml
 pyproject.toml
 README.md
```

## セットアップ
### uv
```bash
cp .env.example .env
cp config.example.yaml config.yaml
uv sync
```

### pip
```bash
cp .env.example .env
cp config.example.yaml config.yaml
pip install -e .[dev]
```

## 実行
```bash
python -m app.main run-once --config config.yaml --env .env
```

`config.yaml` のデフォルトは低頻度アクセスです:
- `request_interval_seconds: 8.0`
- `max_detail_per_listing_page: 3`

## テスト
```bash
pytest -q
```

## cron 実行例
10分ごと:
```cron
*/10 * * * * cd /path/to/iPhoneold && /usr/bin/python -m app.main run-once --config config.yaml --env .env >> logs/monitor.log 2>&1
```

## 実装済み要件
- Scrapling を使う取得抽象 (`app/repositories/fetcher.py`)
- サイト別 parser 分離 (`app/parsers/mercari_public.py`)
- 正規化項目抽出 (`app/extractors/rule_based.py`)
- 除外ルール適用 (`app/services/filtering.py`)
- 粗利推定 (`app/scoring/profit_estimator.py`)
- 危険フラグと risk score (`app/extractors/rule_based.py`)
- Telegram 通知 (`app/notifiers/telegram.py`)
- SQLite 保存 (`app/repositories/item_repository.py`)

## TODO
- 実サイト別 parser の追加
- HTMLセレクタの回帰テスト拡充
- `LLMExtractor` の provider 実装 (qwen/deepseek/openai)
- メトリクス出力やヘルスチェック追加
# iphoneold
