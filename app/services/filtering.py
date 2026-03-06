from __future__ import annotations

from app.config import TargetConfig
from app.models import CandidateItem, SourceItem
from app.utils.text import contains_any, normalize_ws


class ExclusionService:
    def __init__(self, targets: list[TargetConfig]) -> None:
        self.targets = targets

    def apply(self, item: SourceItem) -> CandidateItem:
        text = normalize_ws(f"{item.raw.title} {item.raw.description}").lower()

        if contains_any(text, ["箱のみ", "空箱", "box only", "empty box"]):
            return CandidateItem(raw=item.raw, normalized=item.normalized, exclude_reason="box_only")
        if contains_any(text, ["部品取り", "ジャンク", "junk", "for parts"]):
            return CandidateItem(raw=item.raw, normalized=item.normalized, exclude_reason="junk_or_parts")
        if item.normalized.screen_issue_flag:
            return CandidateItem(raw=item.raw, normalized=item.normalized, exclude_reason="screen_issue")
        if contains_any(text, ["残債あり", "赤ロム", "network ×", "判定×"]):
            return CandidateItem(raw=item.raw, normalized=item.normalized, exclude_reason="network_restriction_risk")
        if not self._target_match(item):
            return CandidateItem(raw=item.raw, normalized=item.normalized, exclude_reason="out_of_target")
        if self._inconsistency_too_high(item):
            return CandidateItem(raw=item.raw, normalized=item.normalized, exclude_reason="title_description_inconsistency")
        return CandidateItem(raw=item.raw, normalized=item.normalized, exclude_reason=None)

    def _target_match(self, item: SourceItem) -> bool:
        for t in self.targets:
            if item.normalized.model_name == t.model and item.normalized.storage_gb == t.storage_gb:
                return True
        return False

    def _inconsistency_too_high(self, item: SourceItem) -> bool:
        title = item.raw.title.lower()
        desc = item.raw.description.lower()
        title_hits = sum(1 for t in self.targets if t.model.lower() in title)
        desc_hits = sum(1 for t in self.targets if t.model.lower() in desc)
        return title_hits > 0 and desc_hits == 0
