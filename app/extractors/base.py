from __future__ import annotations

from abc import ABC, abstractmethod

from app.models import NormalizedFields, RawListing


class Extractor(ABC):
    @abstractmethod
    def extract(self, item: RawListing) -> NormalizedFields:
        raise NotImplementedError
