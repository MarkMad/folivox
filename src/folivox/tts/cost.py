"""Approximate cost of rendering a book with a paid cloud engine (list prices, see ``cloud_apis``)."""

from __future__ import annotations

from folivox.tts.cloud import CHARS_PER_SECOND, generator_class

RETAKE_SHARE = 0.10  # expected share of fragments that fail QA once and are billed again


SAMPLE_BLOCKS = 400  # blocks normalised to measure how much longer the sent text is than the raw text


def book_chars(book, depth: int = 2, selected: list[int] | None = None, preview: int | None = None) -> int:
    """Characters that would be sent for the selected chapters (``selected`` 1-based): the raw text scaled by how
    much the language's normalisation (numbers, dates, abbreviations spelled out) lengthens a sample of it."""
    chosen = [ch for i, ch in enumerate(book.chapters(depth), 1) if not selected or i in selected]
    ratio = _normalised_ratio([b.text for ch in chosen for b in ch.blocks if b.text],
                              getattr(book, "lang", "") or "ru")
    total = 0
    for ch in chosen:
        n = int(round(sum(len(b.text) for b in ch.blocks) * ratio))
        total += min(n, preview) if preview else n  # a preview is capped on the text as sent
    return total


def _normalised_ratio(texts: list[str], lang: str) -> float:
    """Normalised / raw length over an evenly spread sample of blocks; never below 1 (estimate errs high)."""
    if not texts:
        return 1.0
    try:
        from folivox import lang as languages

        normalize = languages.get(lang).normalize
        step = max(1, len(texts) // SAMPLE_BLOCKS)
        sample = texts[::step][:SAMPLE_BLOCKS]
        raw = sum(len(t) for t in sample)
        sent = sum(len(normalize(t)) for t in sample)
    except Exception:  # noqa: BLE001 — an estimate must not fail on a normaliser bug; fall back to the raw count
        return 1.0
    return max(1.0, sent / raw) if raw else 1.0


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
