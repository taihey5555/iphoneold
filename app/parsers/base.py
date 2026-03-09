from __future__ import annotations

from abc import ABC, abstractmethod

from app.models import ListingLink, RawListing


class Parser(ABC):
    def is_allowed_listing_url(self, url: str) -> bool:
        return True

    def is_allowed_item_url(self, url: str) -> bool:
        return True

    @abstractmethod
    def parse_listing(self, html: str) -> list[ListingLink]:
        raise NotImplementedError

    @abstractmethod
    def parse_item(
        self,
        source: str,
        item_url: str,
        html: str,
        notification_text: str | None = None,
    ) -> RawListing:
        raise NotImplementedError
