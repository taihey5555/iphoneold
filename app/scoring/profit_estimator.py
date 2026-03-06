from __future__ import annotations

from app.config import ScoringConfig, TargetConfig
from app.models import CandidateItem, ScoredItem


class ProfitEstimator:
    def __init__(self, targets: list[TargetConfig], scoring: ScoringConfig | None = None) -> None:
        self.targets = targets
        self.scoring = scoring or ScoringConfig()

    def score(self, item: CandidateItem) -> ScoredItem:
        expected, resale_price_reasons = self._expected_resale_price(item)
        purchase_price = item.raw.listed_price + item.raw.shipping_fee
        selling_fee = int(expected * self.scoring.selling_fee_rate)
        shipping_cost = self.scoring.shipping_cost
        risk_buffer = self._risk_buffer(item.normalized.condition_flags, item.normalized.risk_flags)
        estimated_profit = expected - purchase_price - selling_fee - shipping_cost - risk_buffer
        return ScoredItem(
            raw=item.raw,
            normalized=item.normalized,
            exclude_reason=item.exclude_reason,
            expected_resale_price=expected,
            estimated_profit=estimated_profit,
            purchase_price=purchase_price,
            selling_fee=selling_fee,
            shipping_cost=shipping_cost,
            risk_buffer=risk_buffer,
            resale_price_reasons=resale_price_reasons,
        )

    def _expected_resale_price(self, item: CandidateItem) -> tuple[int, list[str]]:
        model = item.normalized.model_name
        storage = item.normalized.storage_gb
        base = 0
        reasons: list[str] = []
        for t in self.targets:
            if t.model == model and t.storage_gb == storage:
                base = t.expected_resale_base
                reasons.append(f"base={t.expected_resale_base}({t.model} {t.storage_gb}GB)")
                break
        if base == 0:
            base = item.raw.listed_price
            reasons.append(f"base=fallback({item.raw.listed_price})")

        if item.normalized.sim_free_flag is True:
            base += self.scoring.sim_free_bonus
            reasons.append(f"sim_free:+{self.scoring.sim_free_bonus}")
        elif item.normalized.sim_free_flag is False:
            base -= self.scoring.sim_locked_penalty
            reasons.append(f"sim_locked:-{self.scoring.sim_locked_penalty}")
        else:
            base -= self.scoring.sim_unknown_penalty
            reasons.append(f"sim_unknown:-{self.scoring.sim_unknown_penalty}")

        carrier = item.normalized.carrier
        if carrier:
            penalty = self.scoring.carrier_penalties.get(carrier, self.scoring.carrier_penalty)
            if penalty > 0:
                base -= penalty
                reasons.append(f"carrier({carrier}):-{penalty}")
        else:
            base -= self.scoring.unknown_carrier_penalty
            reasons.append(f"carrier_unknown:-{self.scoring.unknown_carrier_penalty}")

        if item.normalized.battery_health is not None:
            bh = item.normalized.battery_health
            if bh >= 95:
                base += self.scoring.battery_bonus_95
                reasons.append(f"battery>=95:+{self.scoring.battery_bonus_95}")
            elif bh >= self.scoring.battery_high_threshold:
                base += self.scoring.battery_high_bonus
                reasons.append(f"battery>=high:+{self.scoring.battery_high_bonus}")
            elif bh >= 85:
                base += self.scoring.battery_bonus_85
                reasons.append(f"battery>=85:+{self.scoring.battery_bonus_85}")
            elif bh < 75:
                base -= self.scoring.battery_low_penalty
                reasons.append(f"battery<75:-{self.scoring.battery_low_penalty}")
            elif bh < self.scoring.battery_low_threshold:
                base -= self.scoring.battery_penalty_79
                reasons.append(f"battery<80:-{self.scoring.battery_penalty_79}")
        return max(0, base), reasons

    def _risk_buffer(self, condition_flags: list[str], risk_flags: list[str]) -> int:
        base = self.scoring.base_risk_buffer
        base += len(condition_flags) * self.scoring.condition_flag_buffer
        base += len(risk_flags) * self.scoring.risk_flag_buffer
        return base
