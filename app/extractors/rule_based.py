from __future__ import annotations

import re
import unicodedata

from app.extractors.base import Extractor
from app.models import NormalizedFields, RawListing
from app.utils.text import contains_any, normalize_ws

RISK_SCORE_WEIGHTS = {
    "battery_service": 2,
    "face_id_not_working": 4,
    "non_genuine_display": 3,
    "camera_issue": 3,
    "frame_damage": 3,
    "charging_issue": 3,
    "sim_issue": 3,
    "repair_history": 2,
    "network_restriction_unknown": 2,
    "activation_lock_risk": 5,
    "description_inconsistency": 2,
}

_VALID_STORAGE_GB = {64, 128, 256, 512, 1024}


class RuleBasedExtractor(Extractor):
    def extract(self, item: RawListing) -> NormalizedFields:
        text = normalize_ws(f"{item.title} {item.description} {item.notification_text or ''}")
        lower = text.lower()

        norm = NormalizedFields()
        norm.model_name = _extract_model(text)
        norm.storage_gb = _extract_storage(text)
        norm.color = _extract_color(text)
        norm.carrier = _extract_carrier(text)
        norm.sim_free_flag = _extract_sim_free(lower)
        norm.battery_health = _extract_battery_health(text)
        norm.network_restriction_status = _extract_network_status(lower)
        norm.repair_history_flag = _extract_repair_history_flag(lower)
        norm.face_id_flag = _extract_face_id_flag(lower)
        norm.camera_issue_flag = contains_any(
            lower,
            ["カメラ不良", "カメラ故障", "camera issue", "レンズ割れ", "カメラレンズ割れ", "レンズヒビ"],
        )
        norm.screen_issue_flag = _extract_screen_issue_flag(lower)
        norm.activation_issue_flag = contains_any(lower, ["アクティベーションロック", "activation lock"])
        norm.accessories_flags = _extract_accessories(lower)
        norm.condition_flags = _extract_condition_flags(lower)
        norm.risk_flags, norm.risk_score, norm.risk_score_breakdown = _risk_flags(norm, lower)
        return norm


def _extract_model(text: str) -> str | None:
    lower = text.lower()
    patterns = (
        (r"iphone\s*16\s*pro\s*max", "iPhone 16 Pro Max"),
        (r"iphone\s*16\s*pro", "iPhone 16 Pro"),
        (r"iphone\s*16\s*plus", "iPhone 16 Plus"),
        (r"iphone\s*16(?!\s*(?:pro|max|plus))", "iPhone 16"),
        (r"iphone\s*15\s*pro\s*max", "iPhone 15 Pro Max"),
        (r"iphone\s*15\s*pro", "iPhone 15 Pro"),
        (r"iphone\s*15\s*plus", "iPhone 15 Plus"),
        (r"iphone\s*15(?!\s*(?:pro|max|plus))", "iPhone 15"),
        (r"iphone\s*14\s*pro\s*max", "iPhone 14 Pro Max"),
        (r"iphone\s*14\s*pro", "iPhone 14 Pro"),
        (r"iphone\s*14\s*plus", "iPhone 14 Plus"),
        (r"iphone\s*14(?!\s*(?:pro|max|plus))", "iPhone 14"),
        (r"iphone\s*13\s*pro\s*max", "iPhone 13 Pro Max"),
        (r"iphone\s*13\s*pro", "iPhone 13 Pro"),
        (r"iphone\s*13\s*mini", "iPhone 13 mini"),
        (r"iphone\s*13(?!\s*(?:pro|max|mini))", "iPhone 13"),
        (r"iphone\s*12\s*pro\s*max", "iPhone 12 Pro Max"),
        (r"iphone\s*12\s*pro", "iPhone 12 Pro"),
        (r"iphone\s*12\s*mini", "iPhone 12 mini"),
        (r"iphone\s*12(?!\s*(?:pro|max|mini))", "iPhone 12"),
    )
    for pattern, model in patterns:
        if re.search(pattern, lower):
            return model
    return None


def _extract_storage(text: str) -> int | None:
    normalized = unicodedata.normalize("NFKC", text)
    m = re.search(r"(\d{1,4})\s*(gb|tb)", normalized, flags=re.IGNORECASE)
    if not m:
        return None
    value = int(m.group(1))
    unit = m.group(2).lower()
    if unit == "tb":
        value *= 1024
    return value if value in _VALID_STORAGE_GB else None


def _extract_color(text: str) -> str | None:
    colors = ["ミッドナイト", "スターライト", "ブルー", "ブラック", "ホワイト", "ピンク", "グリーン", "レッド"]
    for c in colors:
        if c in text:
            return c
    return None


def _extract_carrier(text: str) -> str | None:
    normalized = unicodedata.normalize("NFKC", text)
    lower = normalized.lower()
    if contains_any(lower, ["docomo", "ドコモ", "docomo版"]):
        return "docomo"
    if contains_any(lower, ["uq", "uq mobile"]):
        return "au"
    if re.search(r"(?<![a-z0-9])au(?![a-z0-9])", lower) or "au版" in lower:
        return "au"
    if contains_any(lower, ["softbank", "ソフトバンク", "softbank版", "ワイモバイル", "y!mobile", "ymobile"]):
        return "softbank"
    if contains_any(lower, ["楽天", "rakuten", "rakuten mobile"]):
        return "rakuten"
    return None


def _extract_sim_free(text: str) -> bool | None:
    normalized = unicodedata.normalize("NFKC", text).lower()
    if contains_any(normalized, ["simフリー", "sim free", "simfree", "sim-free"]):
        return True
    if contains_any(normalized, ["simロック", "sim lock", "sim-lock"]):
        return False
    return None


def _extract_battery_health(text: str) -> int | None:
    m = re.search(r"(?:バッテリー|battery).{0,8}?(\d{2,3})\s*%", text, flags=re.IGNORECASE)
    if not m:
        return None
    return max(0, min(100, int(m.group(1))))


def _extract_repair_history_flag(text: str) -> bool | None:
    negative_patterns = (
        r"修理歴(?:は|が)?(?:なし|ありません|ございません)",
        r"交換歴(?:は|が)?(?:なし|ありません|ございません)",
        r"修復歴(?:は|が)?(?:なし|ありません|ございません)",
    )
    if any(re.search(pattern, text) for pattern in negative_patterns):
        return False
    positive_words = [
        "修理歴あり",
        "交換歴あり",
        "repair history",
        "修復歴あり",
        "画面交換",
        "バッテリー交換",
        "パネル交換",
        "ディスプレイ交換",
        "非正規修理",
        "修理品",
    ]
    return contains_any(text, positive_words)


def _extract_face_id_flag(text: str) -> bool | None:
    if contains_any(text, ["face id不可", "face id使えない", "face id ng", "face id不良", "face id使えません"]):
        return False
    if contains_any(text, ["face id ok", "face id問題なし", "face id正常", "face id使えます"]):
        return True
    return None


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
        "non_genuine_display": ["非純正ディスプレイ", "非純正画面", "非純正品", "互換パネル", "non genuine display"],
        "frame_damage": ["曲がり", "歪み", "フレーム曲がり", "筐体曲がり"],
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
    if "frame_damage" in norm.condition_flags:
        flags.append("frame_damage")
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
    if contains_any(text, ["説明と写真が違う", "現状優先", "未確認", "本文情報は薄い"]):
        flags.append("description_inconsistency")
    breakdown = {flag: RISK_SCORE_WEIGHTS.get(flag, 0) for flag in flags}
    score = sum(breakdown.values())
    return flags, score, breakdown


def _extract_screen_issue_flag(text: str) -> bool:
    negative_patterns = (
        r"画面割れ(?:は|が)?(?:なし|ありません|ございません)",
        r"液晶不良(?:は|が)?(?:なし|ありません|ございません)",
        r"ひび(?:は|が)?(?:なし|ありません|ございません)",
        r"キズ(?:や|・)?ひびはない",
    )
    if any(re.search(pattern, text) for pattern in negative_patterns):
        return False
    return contains_any(text, ["画面割れ", "液晶不良", "display issue"])
