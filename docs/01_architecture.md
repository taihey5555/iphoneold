# Architecture

## レイヤ
- `app/cli`: 実行入口
- `app/services`: 監視オーケストレーション
- `app/repositories`: 取得層/DB層
- `app/parsers`: サイト別HTML解析
- `app/extractors`: 正規化抽出（将来LLM差し替え）
- `app/scoring`: 粗利計算
- `app/notifiers`: Telegram通知

## 依存方向
- `main -> cli -> services`
- `services -> repositories/parsers/extractors/scoring/notifiers`
- `services` から Scrapling 直接依存しない（`repositories.fetcher` 経由）

## 拡張ポイント
- parser をサイトごとに追加
- fetcher の dynamic 切り替え
- LLM extractor provider 差し替え
