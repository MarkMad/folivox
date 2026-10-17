"""Stretches of another language inside a text, found by Unicode script (no model needed).

Latin words inside Cyrillic text, Cyrillic inside Latin, Han/kana/Hangul inside either: the script says which
language is meant (Latin is guessed between en/de/fr/es/it from function words and accents, English by default).
Same-script languages (English inside German) are not visible here; the markup model tells those.

A run is made of whole words; the spaces, digits and light punctuation *between* its words belong to it, and
punctuation attached to its last word goes with it so the phrase keeps its question or exclamation. Quotes,
brackets, numbers and punctuation at the edges stay with the surrounding text.
"""

from __future__ import annotations

import re
from typing import NamedTuple

from folivox.lang import normalize_code
from folivox.lang.detect import latin_lang

_WORD = re.compile(r"[^\W\d_]+(?:['’\-][^\W\d_]+)*")  # a word, with inner apostrophes and hyphens
_URL = re.compile(r"(?:https?://|www\.)\S+|[\w.+-]+@[\w-]+(?:\.[\w-]+)+", re.IGNORECASE)
_GAP = re.compile(r"[\s\d,;:.!?…\-–'’\"“”«»()]{1,4}$")  # what may lie between two words of one run
_TAIL = ".!?…,;:"  # attached to the last word of a run
_ROMAN = re.compile(r"[IVXLCDM]+$")
_ACRONYM_MAX = 5  # a lone capitalised abbreviation (USB, PDF) is left to the book's own reading rules
_MIN_LETTERS = 3  # a lone foreign word shorter than this is left alone


class Run(NamedTuple):
    start: int
    end: int
    lang: str


def script_of(ch: str) -> str:
    o = ord(ch)
    if 0x0400 <= o <= 0x052F:
        return "cyr"
    if 0x3040 <= o <= 0x30FF:
        return "kana"
    if 0xAC00 <= o <= 0xD7AF or 0x1100 <= o <= 0x11FF:
        return "hangul"
    if 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF:
        return "han"
    if ch.isalpha() and (o < 0x250 or 0x1E00 <= o <= 0x1EFF):
        return "lat"
    return ""


def native_scripts(lang: str) -> frozenset[str]:
    lang = normalize_code(lang)
    if lang in ("ru", "uk", "be", "bg", "sr"):
        return frozenset({"cyr"})
    if lang in ("zh", "ja"):
        return frozenset({"han", "kana"})
    if lang == "ko":
        return frozenset({"hangul", "han"})
    return frozenset({"lat"})


def _word_script(word: str) -> str:
    """The script of the word's letters when they are all of one script, else ``""`` (mixed words are skipped)."""
    seen = {script_of(c) for c in word if c.isalpha()}
    seen.discard("")
    if seen == {"han", "kana"}:  # Japanese mixes kanji and kana inside one unspaced stretch
        return "kana"
    return seen.pop() if len(seen) == 1 else ""


def _lang_of(script: str, word_text: str, book: str) -> str:
    if script == "cyr":
        return "uk" if re.search("[іїєґ]", word_text, re.IGNORECASE) else "ru"
    if script == "hangul":
        return "ko"
    if script == "kana":
        return "ja"
    if script == "han":
        return "ja" if re.search("[぀-ヿ]", word_text) else "zh"
    return latin_lang(word_text)


def script_runs(text: str, book_lang: str) -> list[Run]:
    """Stretches of ``text`` in a language other than ``book_lang`` that show in the script, in text order."""
    native = native_scripts(book_lang)
    book = normalize_code(book_lang)
    banned = [m.span() for m in _URL.finditer(text)]
    words: list[tuple[int, int, str]] = []  # (start, end, script) of words in a foreign script
    for m in _WORD.finditer(text):
        s, e = m.span()
        if any(a <= s < b for a, b in banned):
            continue
        sc = _word_script(m.group())
        if sc and sc not in native:
            words.append((s, e, sc))
    # CJK has no spaces: a stretch of characters is one "word" already (the regex keeps it whole)
    groups: list[list[tuple[int, int, str]]] = []
    for w in words:
        prev = groups[-1][-1] if groups else None
        if prev and _GAP.match(text[prev[1]:w[0]]) and _same_family(prev[2], w[2]):
            groups[-1].append(w)
        else:
            groups.append([w])
    runs: list[Run] = []
    for g in groups:
        start, end = g[0][0], g[-1][1]
        while end < len(text) and text[end] in _TAIL and (end + 1 >= len(text) or not text[end + 1].isalnum()):
            end += 1
        phrase = text[start:end]
        script = g[0][2]
        if len(g) == 1 and script in ("lat", "cyr"):
            letters = sum(c.isalpha() for c in phrase)
            if letters < _MIN_LETTERS or _ROMAN.match(phrase.strip(_TAIL)) or (
                    phrase.strip(_TAIL).isupper() and letters <= _ACRONYM_MAX):
                continue
        lang = _lang_of(script, phrase, book)
        if lang != book:
            runs.append(Run(start, end, lang))
    return runs


def _same_family(a: str, b: str) -> bool:
    cjk = {"han", "kana"}
    return a == b or (a in cjk and b in cjk)



def plausible(part: str, claimed: str, book_lang: str) -> bool:
    """Could ``part`` be in ``claimed``? A claim of a language of another script needs letters of that script; a
    Latin language claimed for Latin text is refused when function words clearly say the book's language."""
    claimed, book = normalize_code(claimed), normalize_code(book_lang)
    scripts = {script_of(c) for c in part if c.isalpha()} - {""}
    if not scripts:
        return False
    want = native_scripts(claimed)
    if claimed in ("zh", "ja", "ko") or want != {"lat"}:
        return bool(scripts & want)
    if "lat" not in scripts:
        return False
    if native_scripts(book) == {"lat"}:
        from folivox.lang.detect import language_scores

        scores = language_scores(part)
        if scores.get(book, 0) >= 2 and scores.get(book, 0) > scores.get(claimed, 0):
            return False
    return True
