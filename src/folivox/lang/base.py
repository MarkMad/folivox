"""Base class for per-language text processing.

A language module subclasses :class:`Language` (or :class:`LatinLanguage` / :class:`CJKLanguage`),
sets a few attributes and overrides what differs, then calls :func:`folivox.lang.register`.
See ``CONTRIBUTING.md`` → "Adding a language".
"""

from __future__ import annotations

import re
import unicodedata

from num2words import num2words

QUOTES = "«»„“”‟\"‘’‚‹›「」『』"
_SPEECH = re.compile(r"[^\W_]", re.UNICODE)  # any letter or digit in any script


class Language:
    code: str = ""  # ISO 639-1, also the Whisper language code
    name: str = ""  # English name
    native: str = ""  # self-name, for UI
    # plausible narration speed in canonical characters per second (QA rejects takes outside)
    cps: tuple[float, float] = (7.0, 23.0)
    chars_per_second: float = 14.0  # source characters per second of audio, for estimates
    # titles for untitled chapters, in the book language
    chapter_label: str = "Chapter {n}"
    intro_label: str = "Introduction"
    # chapter headings in plain text: words before a number ("Chapter 3"), standalone words ("Prologue")
    part_words: tuple[str, ...] = ()
    chapter_words: tuple[str, ...] = ()
    standalone_words: tuple[str, ...] = ()
    # abbreviations ending with "." that do not end a sentence (lowercase, without the dot)
    abbreviations: tuple[str, ...] = ()
    # Whisper hallucinations at the end of audio (regex, matched at the very end, case-insensitive)
    hallucinations: tuple[str, ...] = ()

    # ------------------------------------------------------------ text for the TTS model

    def normalize(self, text: str) -> str:
        """Paragraph → how a narrator reads it: numbers and symbols as words, clean punctuation."""
        return collapse(self.numbers(punctuation(text)))

    def numbers(self, text: str) -> str:
        return re.sub(r"(?<![\w.,])(\d+(?:[.,]\d+)?)(?![\w])", lambda m: self.number(m.group(1)), text)

    def number(self, s: str) -> str:
        try:
            value: float | int = float(s.replace(",", ".")) if re.search(r"[.,]", s) else int(s)
            return num2words(value, lang=self.code)
        except (NotImplementedError, ValueError, OverflowError):
            return s

    def sentences(self, text: str) -> list[str]:
        return split_sentences(text, self.abbreviations)

    def dialogue(self, text: str) -> str:
        """Strip a leading dialogue dash the narrator does not pronounce."""
        return re.sub(r"^\s*[—―]\s*", "", text)

    def stress(self, text: str, mode: str) -> str:
        """Pronunciation hints (Russian ё / stress marks). Most languages need none."""
        return text

    def is_continuation(self, sentence: str) -> bool:
        """True if a split-off sentence actually continues the previous one (dialogue attribution)."""
        first = next((c for c in sentence if c.isalpha()), "")
        return bool(first) and first.islower() and sentence.lstrip()[:1] in "—–-"

    # ------------------------------------------------------------ QA (Whisper comparison)

    def canonical(self, text: str) -> str:
        """Text reduced for CER: numbers as words, lowercase, letters and digits only."""
        text = unicodedata.normalize("NFKC", self.numbers(text)).lower()
        text = "".join(c if (c.isalnum() or c.isspace()) else " " for c in text)
        return " ".join(text.split())


class LatinLanguage(Language):
    def number(self, s: str) -> str:
        # four-digit numbers in running text are almost always years
        if re.fullmatch(r"1[1-9]\d\d|20\d\d", s):
            try:
                return num2words(int(s), lang=self.code, to="year")
            except NotImplementedError:
                pass
        return super().number(s)


class CJKLanguage(Language):
    cps = (2.5, 10.0)
    chars_per_second = 5.0

    def sentences(self, text: str) -> list[str]:
        parts = re.split(r"(?<=[。！？!?…])(?![。！？!?…」』”）)])\s*", text)
        return [p.strip() for p in parts if p.strip()]

    def canonical(self, text: str) -> str:
        return super().canonical(text).replace(" ", "")  # CER per character, spaces are not meaningful

    def is_continuation(self, sentence: str) -> bool:
        return False


# ---------------------------------------------------------------- shared helpers


def punctuation(text: str) -> str:
    text = text.replace("...", "…").replace("--", "—")
    text = re.sub(r"\s[–-]\s", " — ", text)
    text = re.sub(r"^[–-]\s", "— ", text)
    text = re.sub(r"\[\d+\]|\{\d+\}", "", text)
    text = re.sub(f"[{QUOTES}]", "", text)
    text = re.sub(r"\*{1,3}", "", text)
    text = re.sub(r"[_~^|<>]", " ", text)
    text = re.sub(r"\(\s*\)", "", text)
    text = re.sub(r"([!?…])\1+", r"\1", text)
    return text


def collapse(text: str) -> str:
    text = re.sub(r"[ \t  ]+", " ", text)
    text = re.sub(r"\s+([,.!?;:…])", r"\1", text)
    return text.strip()


def has_speech(text: str) -> bool:
    """False for separators like «* * *» that should become a pause."""
    return bool(_SPEECH.search(text))


def split_sentences(text: str, abbreviations: tuple[str, ...] = ()) -> list[str]:
    """Generic splitter: after . ! ? … (plus closing quotes/brackets) followed by space and a
    non-lowercase character; known abbreviations and initials do not end a sentence."""
    abbr = {a.lower() for a in abbreviations}
    out: list[str] = []
    start = 0
    for m in re.finditer(r"[.!?…]+[\"'»”’)\]]*\s+(?=[^\s])", text):
        tokens = text[start:m.start()].split()
        last = tokens[-1].lower() if tokens else ""
        nxt = text[m.end():m.end() + 1]
        if text[m.start()] == "." and (last in abbr or re.fullmatch(r"\w", last) or nxt.islower()):
            continue
        out.append(text[start:m.end()].strip())
        start = m.end()
    tail = text[start:].strip()
    if tail:
        out.append(tail)
    return out
