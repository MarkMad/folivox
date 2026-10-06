"""Guess the language of a text by script and frequent function words (no extra dependencies)."""

from __future__ import annotations

import re
from collections import Counter

STOPWORDS = {
    "en": "the and of to a in that is was he it for with his as had you not but at on her she they",
    "de": "der die und das ist nicht ich sie es zu den mit sich auf ein eine dem war er auch",
    "fr": "le la les et des est une un que il pas du dans qui elle ne se au je sur avec",
    "es": "el la que de y los las en un una del se por con no su para es lo como pero",
    "it": "il la che di e non un una per del gli le si è da con ho lo ma sono della",
}
_SETS = {k: set(v.split()) for k, v in STOPWORDS.items()}


def detect(text: str, default: str = "ru") -> str:
    sample = text[:20000]
    counts = Counter()
    for ch in sample:
        o = ord(ch)
        if 0x0400 <= o <= 0x04FF:
            counts["cyr"] += 1
        elif 0x3040 <= o <= 0x30FF:
            counts["kana"] += 1
        elif 0xAC00 <= o <= 0xD7AF or 0x1100 <= o <= 0x11FF:
            counts["hangul"] += 1
        elif 0x4E00 <= o <= 0x9FFF:
            counts["han"] += 1
        elif ch.isascii() and ch.isalpha() or 0xC0 <= o <= 0x24F:
            counts["lat"] += 1
    if not counts:
        return default
    script = counts.most_common(1)[0][0]
    if script == "cyr":
        return "ru"
    if script == "hangul":
        return "ko"
    if script in ("kana", "han"):
        return "ja" if counts["kana"] > 0.05 * (counts["han"] + counts["kana"]) else "zh"
    words = re.findall(r"[^\W\d_]+", sample.lower())
    scores = {lang: sum(w in s for w in words) for lang, s in _SETS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] else default
