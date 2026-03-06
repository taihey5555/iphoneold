from __future__ import annotations

import re

from app.extractors.base import Extractor
from app.models import NormalizedFields, RawListing
from app.utils.text import contains_any, normalize_ws

RISK_SCORE_WEIGHTS = {
    "battery_service": 2,
    "face_id_not_working": 4,
    "non_genuine_display": 3,
    "camera_issue": 3,
    "charging_issue": 3,
    "sim_issue": 3,
    "repair_history": 2,
    "network_restriction_unknown": 2,
    "activation_lock_risk": 5,
    "description_inconsistency": 2,
}


class RuleBasedExtractor(Extractor):
    def extract(self, item: RawListing) -> NormalizedFields:
        text = normalize_ws(f"{item.title} {item.description}")
        lower = text.lower()

        norm = NormalizedFields()
        norm.model_name = _extract_model(text)
        norm.storage_gb = _extract_storage(text)
        norm.color = _extract_color(text)
        norm.carrier = _extract_carrier(text)
        norm.sim_free_flag = _extract_sim_free(lower)
        norm.battery_health = _extract_battery_health(text)
        norm.network_restriction_status = _extract_network_status(lower)
        norm.repair_history_flag = contains_any(lower, ["修理歴", "交換歴", "repair history", "修復歴"])
        norm.face_id_flag = not contains_any(lower, ["face id不可", "face id使えない", "face id ng"])
        norm.camera_issue_flag = contains_any(lower, ["カメラ不良", "カメラ故障", "camera issue"])
        norm.screen_issue_flag = contains_any(lower, ["画面割れ", "液晶不良", "display issue"])
        norm.activation_issue_flag = contains_any(lower, ["アクティベーションロック", "activation lock"])
        norm.accessories_flags = _extract_accessories(lower)
        norm.condition_flags = _extract_condition_flags(lower)
        norm.risk_flags, norm.risk_score, norm.risk_score_breakdown = _risk_flags(norm, lower)
        return norm


def _extract_model(text: str) -> str | None:
    if "iphone 15" in text.lower():
        return "iPhone 15"
    if "iphone 14" in text.lower():
        return "iPhone 14"
    if "iphone 13" in text.lower():
        return "iPhone 13"
    return None


def _extract_storage(text: str) -> int | None:
    m = re.search(r"(\d{2,4})\s*gb", text, flags=re.IGNORECASE)
    return int(m.group(1)) if m else None


def _extract_color(text: str) -> str | None:
    colors = ["ミッドナイト", "スターライト", "ブルー", "ブラック", "ホワイト", "ピンク", "グリーン", "レッド"]
    for c in colors:
        if c in text:
            return c
    return None


def _extract_carrier(text: str) -> str | None:
    if contains_any(text, ["docomo", "ドコモ"]):
        return "docomo"
    if contains_any(text, ["au"]):
        return "au"
    if contains_any(text, ["softbank", "ソフトバンク"]):
        return "softbank"
    if contains_any(text, ["楽天", "rakuten"]):
        return "rakuten"
    return None


def _extract_sim_free(text: str) -> bool | None:
    if contains_any(text, ["simフリー", "sim free", "simfree"]):
        return True
    if contains_any(text, ["simロック", "sim lock"]):
        return False
    return None


def _extract_battery_health(text: str) -> int | None:
    m = re.search(r"(?:バッテリー|battery).{0,8}?(\d{2,3})\s*%", text, flags=re.IGNORECASE)
    if not m:
        return None
    return max(0, min(100, int(m.group(1))))


def _extract_network_status(text: str) -> str | None:
    if contains_any(text, ["〇", "○", "判定○", "network ok"]):
        return "ok"
    if contains_any(text, ["△", "判定△"]):
        return "pending"
    if contains_any(text, ["×", "判定×", "赤ロム"]):
        return "restricted"
    return "unknown"


def _extract_accessories(text: str) -> list[str]:
    flags: list[str] = []
    if contains_any(text, ["箱あり", "box"]):
        flags.append("box")
    if contains_any(text, ["ケーブル", "cable"]):
        flags.append("cable")
    if contains_any(text, ["本体のみ", "only device"]):
        flags.append("device_only")
    return flags


def _extract_condition_flags(text: str) -> list[str]:
    flags: list[str] = []
    map_words = {
        "battery_service": ["バッテリー修理", "battery service"],
        "non_genuine_display": ["非純正ディスプレイ", "non genuine display"],
        "charging_issue": ["充電不良", "charging issue"],
        "sim_issue": ["sim不良", "sim認識しない"],
    }
    for key, words in map_words.items():
        if contains_any(text, words):
            flags.append(key)
    return flags


def _risk_flags(norm: NormalizedFields, text: str) -> tuple[list[str], int, dict[str, int]]:
    flags: list[str] = []

    if norm.battery_health is not None and norm.battery_health < 80:
        flags.append("battery_service")
    if norm.face_id_flag is False:
        flags.append("face_id_not_working")
    if "non_genuine_display" in norm.condition_flags:
        flags.append("non_genuine_display")
    if norm.camera_issue_flag:
        flags.append("camera_issue")
    if "charging_issue" in norm.condition_flags:
        flags.append("charging_issue")
    if "sim_issue" in norm.condition_flags:
        flags.append("sim_issue")
    if norm.repair_history_flag:
        flags.append("repair_history")
    if norm.network_restriction_status in (None, "unknown"):
        flags.append("network_restriction_unknown")
    if norm.activation_issue_flag:
        flags.append("activation_lock_risk")
    if contains_any(text, ["説明と写真が違う", "現状優先", "未確認"]):
        flags.append("description_inconsistency")
    breakdown = {flag: RISK_SCORE_WEIGHTS.get(flag, 0) for flag in flags}
    score = sum(breakdown.values())
    return flags, score, breakdown
