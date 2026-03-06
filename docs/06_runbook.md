# Runbook

## ローカル実行
1. `cp .env.example .env`
2. `cp config.example.yaml config.yaml`
3. `uv sync` または `pip install -e .[dev]`
4. `python -m app.main run-once --config config.yaml --env .env`

## 定期実行 (cron)
例:
`*/10 * * * * cd /path/to/iPhoneold && /usr/bin/python -m app.main run-once --config config.yaml --env .env >> logs/monitor.log 2>&1`

## 障害時確認
- `errors` カウント増加の有無
- parser selector 破損
- Telegram token/chat_id 設定
- DB書き込み権限
