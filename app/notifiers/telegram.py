from __future__ import annotations

import os
import re

import requests

from app.models import ScoredItem

RISK_FLAG_JA = {
    "network_restriction_unknown": "ネットワーク制限不明",
    "battery_service": "バッテリー要整備",
    "repair_history": "修理歴あり",
    "non_genuine_display": "非純正ディスプレイ",
    "camera_issue": "カメラ不具合",
    "charging_issue": "充電不具合",
    "sim_issue": "SIM関連不具合",
    "face_id_not_working": "Face ID不良",
    "activation_lock_risk": "アクティベーションロック疑い",
    "description_inconsistency": "説明不整合",
}

REASON_TOKEN_JA = {
    "sim_free": "SIMフリー",
    "carrier_unknown": "キャリア不明",
    "carrier(": "キャリア(",
    "network_restriction_unknown": "ネットワーク制限不明",
    "battery_service": "バッテリー要整備",
    "repair_history": "修理歴あり",
    "non_genuine_display": "非純正ディスプレイ",
    "notified_reason": "通知理由",
    "risk_score": "危険度スコア",
    "priority_score": "優先度スコア",
    "profit_current": "粗利現在値",
    "profit_threshold": "粗利閾値",
    "risk_current": "危険度現在値",
    "risk_threshold": "危険度閾値",
}


class TelegramNotifier:
    def __init__(
        self,
        bot_token: str | None = None,
        chat_id: str | None = None,
        mode: str = "detailed",
    ) -> None:
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
        self.mode = mode if mode in {"detailed", "concise"} else "detailed"

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def send_item(self, item: ScoredItem, reason_summary: str) -> None:
        if not self.enabled:
            return
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        text = self.build_message(item, reason_summary)
        requests.post(
            url,
            json={"chat_id": self.chat_id, "text": text, "disable_web_page_preview": True},
            timeout=10,
        ).raise_for_status()

    def build_message(self, item: ScoredItem, reason_summary: str) -> str:
        reason_ja = _to_ja_reason(reason_summary)
        if self.mode == "concise":
            return (
                f"[中古スマホ通知]\n"
                f"{item.raw.title}\n"
                f"価格: {item.raw.listed_price}円 / 想定粗利: {item.estimated_profit}円 / 危険度スコア: {item.normalized.risk_score}\n"
                f"通知理由: {reason_ja}\n"
                f"{item.raw.item_url}"
            )

        risk_flags = ", ".join(_risk_flag_ja(x) for x in item.normalized.risk_flags) if item.normalized.risk_flags else "-"
        risk_breakdown = ", ".join(
            f"{_risk_flag_ja(k)}:{v}" for k, v in item.normalized.risk_score_breakdown.items()
        ) or "-"
        resale_basis = ", ".join(_resale_reason_ja(x) for x in item.resale_price_reasons) if item.resale_price_reasons else "-"
        return (
            f"[中古スマホ通知]\n"
            f"商品名: {item.raw.title}\n"
            f"価格: {item.raw.listed_price}円 (+送料{item.raw.shipping_fee}円)\n"
            f"想定売価: {item.expected_resale_price}円\n"
            f"想定粗利: {item.estimated_profit}円\n"
            f"粗利根拠: {item.expected_resale_price}-({item.purchase_price})-{item.selling_fee}-{item.shipping_cost}-{item.risk_buffer}={item.estimated_profit}\n"
            f"売価根拠: {resale_basis}\n"
            f"危険フラグ: {risk_flags}\n"
            f"危険度スコア内訳: {risk_breakdown} (合計={item.normalized.risk_score})\n"
            f"URL: {item.raw.item_url}\n"
            f"通知理由: {reason_ja}"
        )


def _risk_flag_ja(flag: str) -> str:
    return RISK_FLAG_JA.get(flag, flag)


def _resale_reason_ja(reason: str) -> str:
    out = reason
    out = out.replace("base=", "基準売価=")
    out = out.replace("sim_free", "SIMフリー")
    out = out.replace("carrier_unknown", "キャリア不明")
    out = out.replace("sim_locked", "SIMロック")
    out = out.replace("sim_unknown", "SIM状態不明")
    out = out.replace("battery>=95", "バッテリー95%以上")
    out = out.replace("battery>=high", "バッテリー高水準")
    out = out.replace("battery>=85", "バッテリー85%以上")
    out = out.replace("battery<80", "バッテリー80%未満")
    out = out.replace("battery<75", "バッテリー75%未満")
    out = out.replace("fallback", "フォールバック")
    return out


def _to_ja_reason(reason: str) -> str:
    out = reason or ""
    for k, v in REASON_TOKEN_JA.items():
        out = out.replace(k, v)
    out = out.replace("risk=", "危険度スコア=")
    out = out.replace("profit>=", "想定粗利>=")
    out = out.replace("risk<=", "危険度スコア<=")
    out = re.sub(r"\brisk\b", "危険度", out)
    return out
