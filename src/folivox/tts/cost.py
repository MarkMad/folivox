"""Approximate cost of rendering a book with a paid cloud engine (list prices, see ``cloud_apis``)."""

from __future__ import annotations

from folivox.tts.cloud import CHARS_PER_SECOND, generator_class

RETAKE_SHARE = 0.10  # expected share of fragments that fail QA once and are billed again


def book_chars(book, depth: int = 2, selected: list[int] | None = None, preview: int | None = None) -> int:
    """Characters that would be sent: the text of the selected chapters (``selected`` 1-based)."""
    chapters = book.chapters(depth)
    total = 0
    for i, ch in enumerate(chapters, 1):
        if selected and i not in selected:
            continue
        n = sum(len(b.text) for b in ch.blocks)
        total += min(n, preview) if preview else n
    return total


def estimate(provider: str, chars: int, model: str, takes: int = 2, qa: bool = True, mode: str = "preset",
             lang: str = "") -> dict:
    """``{chars, likely_chars, max_chars_billed, usd, usd_max, per_hour, hours}``; usd values may be None."""
    cls = generator_class(provider)
    takes = max(1, takes if qa else 1)
    likely = int(chars * (1 + RETAKE_SHARE * (takes - 1))) if takes > 1 else chars
    worst = chars * takes

    factor = cls.bytes_factor(lang)  # providers that bill UTF-8 bytes charge more per character outside ASCII

    def usd(n):
        return cls.estimate_for(int(n * factor), 1, mode, model).get("usd")

    hour = CHARS_PER_SECOND * 3600
    return {"provider": provider, "model": model, "chars": chars, "likely_chars": likely,
            "max_chars_billed": worst, "usd": usd(likely), "usd_max": usd(worst), "per_hour": usd(hour),
            "hours": round(chars / hour, 2), "takes": takes, "approximate": True,
            "note": cls.price_note, "terms_url": cls.terms_url}


def describe(e: dict) -> str:
    """One-paragraph plain-English summary for the CLI and the UI."""
    if e["usd"] is None:
        return f"{e['likely_chars']:,} characters will be sent (price not known: see the provider's pricing page)."
    return (f"About {e['hours']:.1f} h of audio, {e['likely_chars']:,} characters sent: ≈ ${e['usd']:.2f} "
            f"(up to ${e['usd_max']:.2f} if every fragment needs all {e['takes']} takes). Approximate list prices.")
