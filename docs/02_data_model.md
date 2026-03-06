# Data Model

## 収集項目
- source
- item_url
- title
- description
- listed_price
- shipping_fee
- posted_at
- seller_name
- image_urls
- fetched_at

## 正規化項目
- model_name
- storage_gb
- color
- carrier
- sim_free_flag
- battery_health
- network_restriction_status
- condition_flags
- repair_history_flag
- face_id_flag
- camera_issue_flag
- screen_issue_flag
- activation_issue_flag
- accessories_flags
- risk_flags
- risk_score

## SQLite
- `items`: 上記 + 粗利関連 + 除外理由
- `notification_history`: 重複通知防止
