# Scraping Strategy

## ポリシー
- 公開ページまたは正式取得可能範囲のみ対象
- robots と利用規約を順守
- rate limiting で過剰アクセス回避
- 初回実URLはメルカリ公開検索/公開商品ページのみ対象

## 実装
- 取得は `ScraplingFetcher` に集約
- デフォルトは HTTP 軽量取得
- 必要時のみ `dynamic=True` に切り替え
- parser は `app/parsers/` に分離
- `mercari_public` parser で許可URLを限定
  - 許可: `/search`, `/item/m...`
  - 除外: ログイン後、購入/売却/取引、`/v1`, `/v2`

## 変更耐性
- parser の CSS selector をサイト単位で局所化
- 取得層と解析層を分けてセレクタ変更の影響範囲を縮小
