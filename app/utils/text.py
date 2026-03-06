from __future__ import annotations

import re


def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def contains_any(text: str, words: list[str]) -> bool:
    t = normalize_ws(text).lower()
    return any(w.lower() in t for w in words)
