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

## 1週間後レビュー手順
1. Telegram 通知を回収する
   - URL と通知文をセットで残す
   - 可能なら `good / bad / watched / bought` も付ける
2. 通知を 3 分類する
   - `当たり`
   - `微妙`
   - `外れ`
3. 外れ通知の理由を 1 行で書く
   - 例: `容量誤抽出` `故障見落とし` `対象外モデル` `本文情報不足` `通知文だけに情報あり`
4. 微妙通知の理由も 1 行で書く
   - 例: `利益薄い` `判定情報が不明` `状態が曖昧`
5. 当たり通知の共通点を見る
   - 例: `SIMフリー` `判定○` `128GB` `バッテリー85%`
6. 外れパターンをルール候補として整理する
   - 例: `通知文の battery 表記も見る`
   - 例: `非純正品を強く減点`
   - 例: `本文情報は薄いを警戒`
7. `rule_based` を先に修正する
   - 安く直せる誤判定を先に潰す
8. 学習用サンプルを 10 件から 30 件作る
   - `url`
   - `notification_text`
   - `title`
   - `description`
   - `期待する抽出結果`
   - `当たり/外れ`
   - `理由`
9. LLM 用の出力 JSON を固定する
   - `model_name`
   - `storage_gb`
   - `sim_free_flag`
   - `battery_health`
   - `network_restriction_status`
   - `risk_flags`
   - `should_notify`
   - `reason`
10. `app/extractors/llm_extractor.py` を実装する
    - 入力は `title + description + notification_text + url`
    - 失敗時は `rule_based` にフォールバックする
11. `rule_based` と LLM を並列比較する
    - 最初は LLM を本番判定に使わず差分を見る
12. 差分を確認して採用範囲を決める
    - `抽出だけ LLM`
    - `微妙案件だけ LLM 再判定`
    - `全面採用`
13. テストを追加して回す
    - 既存テスト
    - 追加した実例テスト
14. 本番へ反映する
    - 精度改善が確認できたら反映する
