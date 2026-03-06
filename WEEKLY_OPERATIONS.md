# 中古スマホbot 1週間運用チェックリスト

## 使い方
- 毎日このファイルを開いて、`[ ]` を `[x]` に変えるだけで運用記録になります。
- 最低1日1回、可能なら朝/昼/夜で確認。

## 事前確認（最初の日だけ）
- [x] `.env` に `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` が設定されている
- [x] `config.yaml` の `max_notifications_per_run` と閾値が自分の運用方針に合っている
- [x] テスト送信が届く（Telegram）



## Day 2
- [ ] 実行: `python -m app.main --config config.yaml --env .env --verbose run-once`
- [ ] 通知と却下理由ログを確認
- [ ] `review-status` 更新
- [ ] `summary` を保存: `python -m app.main --config config.yaml --env .env review-status summary --format json --output reports/day2_summary.json`

## Day 3
- [ ] 実行: `python -m app.main --config config.yaml --env .env --verbose run-once`
- [ ] `review-status list` で recent 確認
- [ ] `review-status` 更新
- [ ] source別 summary 確認

## Day 4
- [ ] 実行
- [ ] 通知精度を確認（false positive が多いか）
- [ ] 必要なら `config.yaml` の notification/scoring を微調整
- [ ] `review-status` 更新

## Day 5
- [ ] 実行
- [ ] `review-status summary --timeseries daily --format tsv` で日次確認
- [ ] `review-status` 更新

## Day 6
- [ ] 実行
- [ ] `review-status summary --timeseries weekly --format csv --output reports/weekly_check.csv`
- [ ] `review-status` 更新

## Day 7
- [ ] 実行
- [ ] 1週間まとめ（good/bad/bought率、平均粗利、source比較）
- [ ] 次週の閾値・重み調整方針を決める

## よく使うコマンド
- 監視1回実行:
  - `python -m app.main --config config.yaml --env .env --verbose run-once`
- recent一覧:
  - `python -m app.main --config config.yaml --env .env review-status list --limit 30 --format tsv`
- ステータス更新:
  - `python -m app.main --config config.yaml --env .env review-status set --source mercari_public --item-url "<URL>" --status good`
- 集計（全体）:
  - `python -m app.main --config config.yaml --env .env review-status summary --format json`
- 集計（時系列）:
  - `python -m app.main --config config.yaml --env .env review-status summary --timeseries both --format tsv`
