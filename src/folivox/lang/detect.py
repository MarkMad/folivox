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
_ACCENTS = {"de": "ßäöü", "fr": "éèêëàâçîïôùûœ", "es": "ñ¿¡áíóú", "it": "ìòùà"}


def language_scores(text: str) -> dict[str, int]:
    """Function-word and accent hits per Latin-script language (en/de/fr/es/it)."""
    words = re.findall(r"[^\W\d_]+", text.lower())
    scores = {lang: sum(w in s for w in words) for lang, s in _SETS.items()}
    low = text.lower()
    for lang, chars in _ACCENTS.items():
        scores[lang] += sum(low.count(c) for c in chars)
    if scores.get("de") and "ß" in low:
        scores["de"] += 2
    return scores


def latin_lang(text: str, default: str = "en") -> str:
    """Which Latin-script language a short text is (en/de/fr/es/it), ``default`` when nothing says."""
    scores = language_scores(text)
    best = max(scores, key=lambda k: (scores[k], k == default))
    return best if scores[best] > scores.get(default, 0) or (scores[best] and best == default) else default


# Scripts that say a likely language by themselves (a suggestion: Arabic script may also be Persian or Urdu)
_OTHER_SCRIPTS = (
    (0x0370, 0x03FF, "el"), (0x0590, 0x05FF, "he"), (0x0600, 0x06FF, "ar"), (0x0750, 0x077F, "ar"),
    (0x0900, 0x097F, "hi"), (0x0980, 0x09FF, "bn"), (0x0E00, 0x0E7F, "th"), (0x10A0, 0x10FF, "ka"),
    (0x0530, 0x058F, "hy"),
)


def _script_counts(text: str) -> Counter:
    counts: Counter = Counter()
    for ch in text:
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
        elif o >= 0x0370:
            for lo, hi, code in _OTHER_SCRIPTS:
                if lo <= o <= hi and ch.isalpha():
                    counts[code] += 1
                    break
    return counts


def shares(text: str, window: int = 800) -> dict[str, float]:
    """The share of letters per language over the whole text, largest first: ``{"ru": 0.92, "en": 0.08}``.
    Scripts say ru/ko/ja/zh; Latin text is told apart by function words per window of ``window`` characters
    (a window that says nothing counts for the Latin language of the text as a whole). Shares under 1% are
    left out."""
    total = _script_counts(text)
    letters = sum(total.values())
    if not letters:
        return {}
    out: Counter = Counter()
    out["ru"] = total["cyr"]
    out["ko"] = total["hangul"]
    for _, _, code in _OTHER_SCRIPTS:
        if total[code]:
            out[code] += total[code]
    cjk = total["han"] + total["kana"]
    if cjk:
        out["ja" if total["kana"] > 0.05 * cjk else "zh"] += cjk
    if total["lat"]:
        per_window: list[tuple[str, int]] = []
        votes: Counter = Counter()
        for i in range(0, len(text), window):
            part = text[i:i + window]
            n = _script_counts(part)["lat"]
            if not n:
                continue
            lang = latin_lang(part, "")
            per_window.append((lang, n))
            if lang:
                votes[lang] += n
        main = votes.most_common(1)[0][0] if votes else "en"
        for lang, n in per_window:
            out[lang or main] += n
    return {k: round(v / letters, 4) for k, v in out.most_common() if v / letters >= 0.01}


def detect(text: str, default: str = "ru") -> str:
    """The most likely language by script and function words; a script of one of the languages without
    rules (Arabic, Devanagari, Thai, Greek, …) gives that language's code, never Russian."""
    sample = text[:20000]
    counts = _script_counts(sample)
    if not counts:
        return default
    script = counts.most_common(1)[0][0]
    if script == "cyr":
        return "ru"
    if script == "hangul":
        return "ko"
    if script in ("kana", "han"):
        return "ja" if counts["kana"] > 0.05 * (counts["han"] + counts["kana"]) else "zh"
    if script != "lat":
        return script
    # Latin script: function words and accents; "en" when nothing says (never the Cyrillic default)
    return latin_lang(sample, "en")


_UK = set("іїєґІЇЄҐ")
_BE = set("ўЎ")


def unsupported_cyrillic(text: str) -> str | None:
    """"uk" or "be" when Cyrillic text looks Ukrainian / Belarusian rather than Russian, else None.
    Cheap letter shares: і/ї/є/ґ (uk) or ў (be) among Cyrillic letters; Russian has none of them."""
    cyr = uk = be = 0
    for ch in text[:50000]:
        if "\u0400" <= ch <= "\u04ff":
            cyr += 1
            if ch in _UK:
                uk += 1
            elif ch in _BE:
                be += 1
    if cyr < 200:
        return None
    if be >= 0.003 * cyr:
        return "be"
    if uk >= 0.02 * cyr:
        return "uk"
    return None
