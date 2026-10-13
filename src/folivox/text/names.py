"""Names a book is likely to need a pronunciation for: capitalised words that keep their capital mid-sentence.

A word counts when it is written with a capital often enough away from the start of a sentence and (almost)
never in lower case. Every form is listed on its own (``Kvothe``, ``Kvothe's``-stripped), because the stress
and the respelling of the forms can differ.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from folivox import lang as languages
from folivox.book import Book

_WORD = re.compile(r"[^\W\d_](?:[^\W\d_]|['’\-][^\W\d_])*", re.UNICODE)
_SENTENCE_START = re.compile(r"(?:^|[.!?…:]\s+|[«“\"(\[—–]\s*)$")
_POSSESSIVE = re.compile(r"['’]s$", re.IGNORECASE)
_SCRIPTS_WITHOUT_CAPITALS = ("zh", "ja", "ko")
# capitalised everywhere in running text without being a name of a person or a place
_COMMON = {"god", "mr", "mrs", "ms", "dr", "sir", "lord", "lady", "monday", "tuesday", "wednesday", "thursday",
           "friday", "saturday", "sunday", "english", "french", "german", "spanish", "italian", "russian"}


@dataclass(frozen=True)
class Candidate:
    word: str
    count: int  # capitalised occurrences away from the start of a sentence


def candidates(book: Book, *, min_count: int = 3, lang: str | None = None) -> list[Candidate]:
    code = lang or book.lang or "ru"
    if code in _SCRIPTS_WITHOUT_CAPITALS:
        return []
    skip = _COMMON | {m.lower() for m in getattr(languages.get(code), "months", ())}
    capital: Counter[str] = Counter()
    lower: Counter[str] = Counter()
    for chapter in book.chapters(max_depth=99):
        for block in chapter.blocks:
            text = block.text
            for m in _WORD.finditer(text):
                word = _POSSESSIVE.sub("", m.group(0))
                if len(word) < 3:
                    continue
                if word[0].isupper() and not word.isupper():
                    if not _SENTENCE_START.search(text[:m.start()]):
                        capital[word] += 1
                elif word[0].islower():
                    lower[word] += 1
    out = []
    for word, n in capital.items():
        if n < min_count or word.lower() in skip:
            continue
        if lower[word.lower()] > 0.1 * (n + lower[word.lower()]):  # also an ordinary word: not a name
            continue
        out.append(Candidate(word, n))
    return sorted(out, key=lambda c: (-c.count, c.word))
