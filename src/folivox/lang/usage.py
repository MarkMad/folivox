"""Which languages each speaker of a book reads, and whether their voice can read them."""

from __future__ import annotations

from collections import Counter

from folivox import markup as mk
from folivox.book import BlockKind

MIN_LETTERS = 12  # a language with fewer letters than this in a speaker's text is not worth a warning
MIN_SHARE = 0.02


def speaker_languages(chapters: list, markup: mk.Markup | None, book_lang: str) -> dict[int, Counter]:
    """Letters per language of what every speaker reads, over the whole book: ``{speaker id: {lang: letters}}``.
    A fragment without a language of its own is in the book's language."""
    markup = markup or mk.Markup()
    out: dict[int, Counter] = {}
    for ci, ch in enumerate(chapters):
        for bi, b in enumerate(ch.blocks):
            if b.kind == BlockKind.POEM:  # poems are read whole, in the book's language
                out.setdefault(0, Counter())[book_lang] += sum(c.isalpha() for c in b.text)
                continue
            for seg in markup.segments(ci, bi, b.text, book_lang):
                n = sum(c.isalpha() for c in seg.text)
                if n:
                    out.setdefault(seg.speaker, Counter())[seg.lang or book_lang] += n
    return out


def significant(used: dict[str, int]) -> list[str]:
    """The languages of a speaker's text that matter, largest first."""
    total = sum(used.values())
    return [k for k, v in sorted(used.items(), key=lambda kv: -kv[1]) if v >= MIN_LETTERS and v >= MIN_SHARE * total]


def voice_gaps(used: dict[str, int], voice_lang: str) -> list[str]:
    """Languages of a speaker's text that the voice does not speak (a voice speaks the language of its sample; any
    other it reads with that accent). Only for a speaker who reads more than one language: a one-language text
    in a voice of another language is a choice the voice picker already marks."""
    langs = significant(used)
    if len(langs) < 2 or not voice_lang:
        return []
    return [lang for lang in langs if lang != voice_lang]
