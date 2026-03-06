# Scoring Logic

## 粗利式
`estimated_profit = expected_resale_price - purchase_price - selling_fee - shipping_cost - risk_buffer`

## MVP売価推定
- 対象機種ごとのベース売価を `config.yaml` で定義
- SIMフリー +1500
- キャリア縛り -1000
- バッテリー90%以上 +1200
- バッテリー80%未満 -3500

## リスクバッファ
- 基本 1000 円
- `condition_flags` ごとに +600
- `risk_flags` ごとに +800
