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
- `max_notifications_per_run: 3`
- `notification_mode: detailed` (`concise` で短文通知)

## テスト
```bash
pytest -q
```

## review_status 運用コマンド
更新:
```bash
python -m app.main review-status set --source mercari_public --item-url "https://jp.mercari.com/item/m123" --status good
python -m app.main review-status set --source mercari_public --item-url "https://jp.mercari.com/item/m123" --status watched --note "IMEI未確認のため保留"
```

結果記録:
```bash
python -m app.main review-status outcome-set --source mercari_public --item-url "https://jp.mercari.com/item/m123" --outcome bought
python -m app.main review-status outcome-set --source mercari_public --item-url "https://jp.mercari.com/item/m123" --outcome sold --exit-channel mercari_resale --sale-price 69800 --note "2日で売却"
python -m app.main review-status outcome-set --source mercari_public --item-url "https://jp.mercari.com/item/m123" --outcome buyback_done --exit-channel buyback_shop --sale-price 61500
```

日報同期:
```bash
python -m app.main review-status daily-notes-sync --date 2026-03-09 --day 4 --notes-file daily_notes.md
```

一覧 (recent):
```bash
python -m app.main review-status list --limit 20
python -m app.main review-status list --source mercari_public --status pending --limit 30
python -m app.main review-status list --format csv --limit 50
python -m app.main review-status list --format json --status good --limit 20
```

集計 (summary):
```bash
python -m app.main review-status summary
python -m app.main review-status summary --source mercari_public
python -m app.main review-status summary --status good --format json
python -m app.main review-status summary --format tsv --output reports/review_summary.tsv
python -m app.main review-status performance --format tsv
python -m app.main review-status performance --exit-channel buyback_shop --format json
```

source別分析:
```bash
python -m app.main review-status summary --format json
python -m app.main review-status summary --source mercari_public --format tsv
python -m app.main review-status summary --timeseries daily --format tsv
python -m app.main review-status summary --timeseries weekly --format csv --output reports/review_weekly.csv
```

出力保存 (--output):
```bash
python -m app.main review-status list --format csv --limit 100 --output reports/recent_items.csv
python -m app.main review-status list --format json --status good --output reports/good_items.json
```

## cron 実行例
10分ごと:
```cron
*/10 * * * * cd /path/to/iPhoneold && /usr/bin/python -m app.main run-once --config config.yaml --env .env >> logs/monitor.log 2>&1
```

## 実装済み要件
- Scrapling を使う取得抽象 (`app/repositories/fetcher.py`)
- サイト別 parser 分離 (`app/parsers/mercari_public.py`)
- `mercari_public` は商品説明DOMを優先し、メルカリ汎用 `meta description` は説明文として極力採用しない
- 正規化項目抽出 (`app/extractors/rule_based.py`)
- 除外ルール適用 (`app/services/filtering.py`)
- `画面割れなし` `修理歴なし` `付属品は箱のみ` のような否定/付属品文脈での誤除外を抑制
- 粗利推定 (`app/scoring/profit_estimator.py`)
- 危険フラグと risk score (`app/extractors/rule_based.py`)
- Telegram 通知 (`app/notifiers/telegram.py`)
- SQLite 保存 (`app/repositories/item_repository.py`)

## TODO
- 実サイト別 parser の追加
- HTMLセレクタの回帰テスト拡充
- `LLMExtractor` の provider 実装 (qwen/deepseek/openai)
- メトリクス出力やヘルスチェック追加

## 現在のMVPの限界
- メルカリはフロント変更頻度が高く、セレクタ/JSON-LD依存のため将来の破損余地がある
- 価格推定はルールベースで、相場急変や季節性を十分反映しない
- `risk_flags` は文面依存のため、出品者の表現ゆれに対して誤判定の余地がある
- 否定表現や付属品説明の扱いは改善済みだが、表現ゆれ次第では誤検知が残る
- 類似重複抑制はキー近似（モデル/容量/価格帯）であり、完全一致保証ではない
- 動的取得は遅く、環境依存の失敗（タイムアウト・ブラウザ依存）が発生しうる

## 推奨運用フロー
1. `run-once` 実行後、通知を利益順で確認する
2. 通知文の `粗利根拠` と `risk内訳` を見て一次判断する
3. 実際の商品ページでIMEI状態・付属品・写真整合性を最終確認する
4. 仕入れ判断結果を `review_status` で記録する
   - 例: `pending` / `watched` / `good` / `bad` / `bought`
5. 実際に仕入れた案件は `outcome-set` で出口と実粗利を記録する
   - 例: `bought` / `sold` / `buyback_done` / `loss` / `passed`
5. 週次で `false_positive` を見直し、`notification.risk_priority_weights` と閾値を調整する
# iphoneold
