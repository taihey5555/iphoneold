from __future__ import annotations

import logging
from dataclasses import dataclass

from app.config import Settings, SourceConfig
from app.extractors.base import Extractor
from app.models import ScoredItem, SourceItem
from app.notifiers.telegram import TelegramNotifier
from app.parsers import build_parser
from app.repositories import ItemRepository, MarketplaceFetcher
from app.scoring import ProfitEstimator
from app.services.filtering import ExclusionService
from app.utils.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


@dataclass
class RunStats:
    fetched: int = 0
    excluded: int = 0
    notified: int = 0
    errors: int = 0


class MonitorService:
    def __init__(
        self,
        settings: Settings,
        fetcher: MarketplaceFetcher,
        extractor: Extractor,
        repository: ItemRepository,
        notifier: TelegramNotifier,
    ) -> None:
        self.settings = settings
        self.fetcher = fetcher
        self.extractor = extractor
        self.repository = repository
        self.notifier = notifier
        self.filtering = ExclusionService(settings.targets)
        self.estimator = ProfitEstimator(settings.targets, settings.scoring)
        self.rate_limiter = RateLimiter(settings.app.request_interval_seconds)

    def run_once(self) -> RunStats:
        stats = RunStats()
        notify_candidates: list[ScoredItem] = []
        for source in self.settings.sources:
            if not source.enabled:
                continue
            notify_candidates.extend(self._process_source(source, stats))
        self._send_notifications(notify_candidates, stats)
        return stats

    def _process_source(self, source: SourceConfig, stats: RunStats) -> list[ScoredItem]:
        notify_candidates: list[ScoredItem] = []
        parser = build_parser(source.parser, sample_url=source.listing_urls[0] if source.listing_urls else None)
        for listing_url in source.listing_urls:
            if not parser.is_allowed_listing_url(listing_url):
                logger.warning("skip non-allowed listing url: source=%s url=%s", source.name, listing_url)
                continue
            try:
                self.rate_limiter.wait()
                listing_html = self.fetcher.fetch(listing_url, dynamic=False).html
                links = parser.parse_listing(listing_html)
                if not links and self.settings.app.use_dynamic_fetch:
                    logger.info("listing links empty on HTTP fetch, retrying dynamic: %s", listing_url)
                    self.rate_limiter.wait()
                    listing_html = self.fetcher.fetch(listing_url, dynamic=True).html
                    links = parser.parse_listing(listing_html)
            except Exception as exc:
                logger.exception("listing fetch failed: source=%s url=%s err=%s", source.name, listing_url, exc)
                stats.errors += 1
                continue

            for link in links[: self.settings.app.max_detail_per_listing_page]:
                if not parser.is_allowed_item_url(link.url):
                    logger.info("skip non-allowed item url: source=%s url=%s", source.name, link.url)
                    continue
                try:
                    self.rate_limiter.wait()
                    detail_html = self.fetcher.fetch(link.url, dynamic=self.settings.app.use_dynamic_fetch).html
                    raw = parser.parse_item(source=source.name, item_url=link.url, html=detail_html)
                    normalized = self.extractor.extract(raw)
                    source_item = SourceItem(raw=raw, normalized=normalized)
                    candidate = self.filtering.apply(source_item)
                    scored = self.estimator.score(candidate)
                    self.repository.upsert_scored_item(scored)
                    self._debug_item_summary(scored)
                    stats.fetched += 1
                    if scored.exclude_reason is not None:
                        stats.excluded += 1
                        self._log_rejection(scored, self._exclude_reason_code(scored.exclude_reason))
                        continue
                    should_notify, reason = self._should_notify(scored)
                    scored.notification_reason = reason
                    if should_notify:
                        logger.debug("candidate eligible: url=%s reason=%s", scored.raw.item_url, reason)
                        notify_candidates.append(scored)
                    else:
                        self._log_rejection(scored, reason)
                except Exception as exc:
                    logger.exception("detail processing failed: source=%s url=%s err=%s", source.name, link.url, exc)
                    stats.errors += 1
        return notify_candidates

    def _should_notify(self, item: ScoredItem) -> tuple[bool, str]:
        blocked = [f for f in item.normalized.risk_flags if f in self.settings.notification.never_notify_flags]
        if blocked:
            return False, f"never_notify_flag(flags={','.join(blocked)})"

        if item.estimated_profit < self.settings.app.min_profit_yen:
            return (
                False,
                f"profit_below_threshold(current={item.estimated_profit},threshold={self.settings.app.min_profit_yen})",
            )
        if item.normalized.risk_score > self.settings.app.max_risk_score:
            return (
                False,
                f"risk_too_high(current={item.normalized.risk_score},threshold={self.settings.app.max_risk_score})",
            )

        if self._is_network_unknown_only(item):
            stricter_profit = self.settings.app.min_profit_yen + self.settings.notification.network_unknown_only_extra_profit
            if item.estimated_profit < stricter_profit:
                return (
                    False,
                    f"network_unknown_strict_rule(metric=profit,current={item.estimated_profit},threshold={stricter_profit})",
                )
            if item.normalized.risk_score > self.settings.notification.network_unknown_only_max_risk_score:
                return (
                    False,
                    "network_unknown_strict_rule("
                    f"metric=risk,current={item.normalized.risk_score},"
                    f"threshold={self.settings.notification.network_unknown_only_max_risk_score})",
                )

        dedupe_key = self._dedupe_key(item)
        similarity_key = self._similarity_key(item)
        if self.repository.has_recent_notification(
            source=item.raw.source,
            item_url=item.raw.item_url,
            window_minutes=self.settings.app.duplicate_window_minutes,
            dedupe_key=dedupe_key,
            similarity_key=similarity_key,
        ):
            return False, f"recent_duplicate(dedupe_key={dedupe_key},similarity_key={similarity_key})"
        reason = (
            f"notified_reason(profit_current={item.estimated_profit},profit_threshold={self.settings.app.min_profit_yen}, "
            f"risk_current={item.normalized.risk_score},risk_threshold={self.settings.app.max_risk_score}, "
            f"target={item.normalized.model_name} {item.normalized.storage_gb}GB, "
            f"priority_score={self._priority_score(item)})"
        )
        return True, reason

    def _send_notifications(self, candidates: list[ScoredItem], stats: RunStats) -> None:
        if not candidates:
            return
        ranked = sorted(candidates, key=lambda x: (self._priority_score(x), x.estimated_profit), reverse=True)
        limit = max(0, self.settings.app.max_notifications_per_run)
        in_run_keys: set[str] = set()
        for item in ranked:
            if stats.notified >= limit:
                reason = f"max_notifications_per_run(current={stats.notified},limit={limit})"
                item.notification_reason = reason
                self._log_rejection(item, reason)
                continue
            dedupe_key = self._dedupe_key(item)
            similarity_key = self._similarity_key(item)
            if dedupe_key in in_run_keys or similarity_key in in_run_keys:
                reason = f"recent_duplicate(in_run=true,dedupe_key={dedupe_key},similarity_key={similarity_key})"
                item.notification_reason = reason
                self._log_rejection(item, reason)
                continue
            in_run_keys.add(dedupe_key)
            in_run_keys.add(similarity_key)
            reason = self._notify_reason(item)
            item.notification_reason = reason
            self.notifier.send_item(item, reason)
            self.repository.mark_notified(
                item.raw.source,
                item.raw.item_url,
                dedupe_key=dedupe_key,
                similarity_key=similarity_key,
            )
            stats.notified += 1
            logger.debug("candidate notified: url=%s notified_reason=%s", item.raw.item_url, reason)

    def _notify_reason(self, item: ScoredItem) -> str:
        risk_parts = ", ".join(
            f"{flag}:{score}" for flag, score in item.normalized.risk_score_breakdown.items()
        ) or "-"
        resale_basis = ", ".join(item.resale_price_reasons) or "-"
        return (
            f"なぜ通知: profit/risk基準を満たしたため。"
            f"粗利式={item.expected_resale_price}-"
            f"({item.purchase_price})-{item.selling_fee}-{item.shipping_cost}-{item.risk_buffer}"
            f"={item.estimated_profit}。"
            f"売価根拠=[{resale_basis}]。"
            f"risk={item.normalized.risk_score} 内訳=[{risk_parts}]。"
            f"閾値: profit>={self.settings.app.min_profit_yen}, risk<={self.settings.app.max_risk_score}"
        )

    @staticmethod
    def _dedupe_key(item) -> str:
        seller = item.raw.seller_name or "-"
        model = item.normalized.model_name or "unknown"
        storage = item.normalized.storage_gb or 0
        rounded_price = int(round(item.raw.listed_price / 1000.0) * 1000)
        return f"{item.raw.source}|{model}|{storage}|{rounded_price}|{seller}"

    @staticmethod
    def _similarity_key(item) -> str:
        model = item.normalized.model_name or "unknown"
        storage = item.normalized.storage_gb or 0
        rounded_price = int(round(item.raw.listed_price / 2000.0) * 2000)
        return f"{item.raw.source}|{model}|{storage}|{rounded_price}"

    def _debug_item_summary(self, item: ScoredItem) -> None:
        logger.debug(
            "item summary: source=%s url=%s model=%s storage=%s price=%s shipping=%s "
            "expected=%s profit=%s risk_score=%s priority=%s risk_flags=%s exclude=%s",
            item.raw.source,
            item.raw.item_url,
            item.normalized.model_name,
            item.normalized.storage_gb,
            item.raw.listed_price,
            item.raw.shipping_fee,
            item.expected_resale_price,
            item.estimated_profit,
            item.normalized.risk_score,
            self._priority_score(item),
            ",".join(item.normalized.risk_flags),
            item.exclude_reason,
        )

    def _log_rejection(self, item: ScoredItem, reason: str) -> None:
        logger.debug(
            "candidate rejected: source=%s url=%s reason=%s",
            item.raw.source,
            item.raw.item_url,
            reason,
        )

    def _priority_score(self, item: ScoredItem) -> int:
        score = item.estimated_profit
        for flag in item.normalized.risk_flags:
            score += self.settings.notification.risk_priority_weights.get(flag, 0)
        return score

    @staticmethod
    def _is_network_unknown_only(item: ScoredItem) -> bool:
        flags = item.normalized.risk_flags
        return len(flags) == 1 and flags[0] == "network_restriction_unknown"

    @staticmethod
    def _exclude_reason_code(exclude_reason: str) -> str:
        if exclude_reason == "out_of_target":
            return "not_target_model"
        return f"excluded_by_rule(rule={exclude_reason})"
