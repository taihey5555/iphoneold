from __future__ import annotations

from app.extractors.base import Extractor
from app.models import NormalizedFields, RawListing


class LLMExtractor(Extractor):
    """Provider-agnostic placeholder.

    Future providers: qwen / deepseek / openai.
    """

    def __init__(self, provider: str) -> None:
        self.provider = provider

    def extract(self, item: RawListing) -> NormalizedFields:
        raise NotImplementedError("LLM extractor is not implemented in MVP.")
