from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


@dataclass(frozen=True)
class TargetConfig:
    model: str
    storage_gb: int
    keywords: list[str]
    expected_resale_base: int


@dataclass(frozen=True)
class SourceConfig:
    name: str
    enabled: bool
    listing_urls: list[str]
    parser: str


@dataclass(frozen=True)
class AppConfig:
    timezone: str
    min_profit_yen: int
    max_risk_score: int
    duplicate_window_minutes: int
    fetch_timeout_seconds: int
    request_interval_seconds: float
    use_dynamic_fetch: bool
    db_path: str
    max_detail_per_listing_page: int = 3
    max_notifications_per_run: int = 3
    notification_mode: str = "detailed"


@dataclass(frozen=True)
class ScoringConfig:
    selling_fee_rate: float = 0.1
    shipping_cost: int = 750
    base_risk_buffer: int = 1000
    condition_flag_buffer: int = 600
    risk_flag_buffer: int = 800
    sim_free_bonus: int = 1500
    carrier_penalty: int = 1000
    carrier_penalties: dict[str, int] = field(
        default_factory=lambda: {"docomo": 1200, "au": 1000, "softbank": 1000, "rakuten": 600}
    )
    sim_locked_penalty: int = 1800
    sim_unknown_penalty: int = 700
    unknown_carrier_penalty: int = 500
    battery_high_threshold: int = 90
    battery_high_bonus: int = 1200
    battery_low_threshold: int = 80
    battery_low_penalty: int = 3500
    battery_bonus_95: int = 1800
    battery_bonus_85: int = 500
    battery_penalty_79: int = 1500


@dataclass(frozen=True)
class NotificationConfig:
    risk_priority_weights: dict[str, int] = field(
        default_factory=lambda: {
            "network_restriction_unknown": -1200,
            "battery_service": -600,
            "repair_history": -900,
            "non_genuine_display": -1300,
            "camera_issue": -1500,
            "charging_issue": -1300,
            "sim_issue": -1400,
            "face_id_not_working": -1800,
            "activation_lock_risk": -3000,
            "description_inconsistency": -700,
        }
    )
    never_notify_flags: list[str] = field(default_factory=lambda: ["activation_lock_risk"])
    network_unknown_only_extra_profit: int = 2500
    network_unknown_only_max_risk_score: int = 2


@dataclass(frozen=True)
class Settings:
    app: AppConfig
    scoring: ScoringConfig
    targets: list[TargetConfig]
    sources: list[SourceConfig]
    notification: NotificationConfig = field(default_factory=NotificationConfig)

    @classmethod
    def load(cls, config_path: str = "config.yaml", env_path: str = ".env") -> "Settings":
        load_dotenv(env_path, override=False)
        config_data = _read_yaml(config_path)
        app_cfg = AppConfig(**config_data["app"])
        scoring_cfg = ScoringConfig(**config_data.get("scoring", {}))
        notification_cfg = NotificationConfig(**config_data.get("notification", {}))
        targets = [TargetConfig(**row) for row in config_data.get("targets", [])]
        sources = [SourceConfig(**row) for row in config_data.get("sources", [])]
        return cls(
            app=app_cfg,
            scoring=scoring_cfg,
            targets=targets,
            sources=sources,
            notification=notification_cfg,
        )


def _read_yaml(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
