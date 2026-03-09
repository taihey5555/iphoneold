# Session Start
<!-- これを最初に読み込ませる
SESSION_START.md を読んで続きから進めて  -->

## このプロジェクトの目的
- 中古 iPhone の公開出品を監視して、仕入れ候補を Telegram 通知する
- 今は通知品質と抽出精度を上げるためのデータ収集フェーズ

## 今の状態
- `URL + notification_text` を使う実装に変更済み
- まずは 1 週間、通知の当たり外れを貯める
- まだ買取屋価格の細かい追い込みはしない

## 毎回最初に確認するファイル
- `daily_notes.md`
- `docs/06_runbook.md`

## 毎日の運用
- Telegram 通知を確認する
- `good / bad / watched / bought` を更新する
- 気づいた誤判定や情報不足を `daily_notes.md` に残す

## 1週間後にやること
- 通知を `当たり / 微妙 / 外れ` に分類する
- 外れパターンを整理する
- `rule_based` を先に改善する
- 必要なら `app/extractors/llm_extractor.py` に DeepSeek などの LLM を導入する

## 次回セッション開始時の指示
以下を読んでから続きに入ること。

1. `SESSION_START.md`
2. `daily_notes.md`
3. `docs/06_runbook.md`

そのうえで、現在がデータ収集フェーズか、1週間後レビュー後かを判断して次の作業を進めること。
