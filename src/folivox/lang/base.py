"""Base class for per-language text processing.

A language module subclasses :class:`Language` (or :class:`LatinLanguage` / :class:`CJKLanguage`),
sets a few attributes and overrides what differs, then calls :func:`folivox.lang.register`.
See ``CONTRIBUTING.md`` → "Adding a language".
"""

from __future__ import annotations

import re
import unicodedata

from num2words import num2words

from folivox.lang.rules import (
    AMOUNT,
    MONEY_SYMBOLS,
    ROMAN_LOOSE,
    ROMAN_RE,
    parse_amount,
    phones,
    prev_token,
    prev_word,
    roman_to_int,
    unit_regex,
)

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
        except (NotImplementedError, ValueError, OverflowError, KeyError, IndexError):  # huge numbers
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
    """Alphabetic languages: one pipeline (abbreviations → romans → dates → times → money → units →
    ordinals → gender agreement → symbols → plain numbers); each language fills in data and hooks."""

    SYMBOLS: dict[str, str] = {}
    thousands_re: str = ""  # thousands separators to strip («10.000», «10,000», «10 000»)
    abbreviation_map: tuple[tuple[str, str], ...] = ()  # (regex, expansion), «Dr\\.» → «Doctor»
    months: tuple[str, ...] = ()
    roman_words: tuple[str, ...] = ()  # words before a roman numeral read as a cardinal: «Chapter IV»
    century_after: tuple[str, ...] = ()  # «XIX century»
    century_before: tuple[str, ...] = ()  # «siglo XIX»
    century_suffix: str = ""  # «XXe siècle»
    fem_names: tuple[str, ...] = ()  # queens and such: «Isabel II» → «segunda»
    roman_dot: bool = False  # «Ludwig XIV.» (German ordinal dot)
    time_preps: tuple[str, ...] = ()
    currencies: dict[str, tuple] = {}  # key → (one, many, sub_one, sub_many, feminine)
    currency_words: bool = True  # «5,50 euros» is read as money too
    money_join: str = " "
    money_scales: tuple[str, ...] = ()  # «$5 million»
    units: dict[str, tuple[str, str]] = {}
    plus_word: str = "plus"

    def numbers(self, text: str) -> str:
        if self.thousands_re:
            text = re.sub(self.thousands_re, "", text)
        text = self.expand_abbreviations(text)
        text = self.romans(text)
        text = self.dates(text)
        text = self.times(text)
        text = self.money(text)
        text = phones(text, self.number, self.plus_word)
        text = self.measures(text)
        text = self.ordinals(text)
        text = self.agreement(text)
        for k, v in self.SYMBOLS.items():
            text = text.replace(k, v)
        return super().numbers(text)

    def number(self, s: str) -> str:
        # four-digit numbers in running text are almost always years
        if re.fullmatch(r"1[1-9]\d\d|20\d\d", s):
            try:
                return num2words(int(s), lang=self.code, to="year")
            except NotImplementedError:
                pass
        return super().number(s)

    # ---- hooks

    def cardinal_noun(self, n: int, feminine: bool = False) -> str:
        """A cardinal before a noun («un», «una», «ein»)."""
        return num2words(n, lang=self.code)

    def ordinal_word(self, n: int, feminine: bool = False) -> str:
        return num2words(n, lang=self.code, to="ordinal")

    def roman_cardinal(self, n: int) -> str:
        return self.number(str(n))

    def roman_regnal(self, n: int, name: str) -> str:
        return self.roman_cardinal(n)

    def roman_century(self, n: int, ctx: str = "") -> str:
        return self.roman_cardinal(n)

    def time_words(self, h: int, m: int, meridiem: str | None) -> str:
        return f"{self.number(str(h))} {self.number(str(m))}" if m else self.number(str(h))

    def dates(self, text: str) -> str:
        return text

    def ordinals(self, text: str) -> str:
        return text

    def agree(self, n: int, word: str) -> str | None:
        """Cardinal for ``n`` agreeing with the noun that follows, or None to leave it to num2words."""
        return None

    def is_plural(self, value: float) -> bool:
        return value != 1

    # ---- steps

    def expand_abbreviations(self, text: str) -> str:
        for pat, rep in self.abbreviation_map:
            tail = "" if "(?=" in pat else r"(?!\w)"
            text = re.sub(rf"(?<!\w){pat}{tail}", rep, text)
        return text

    def romans(self, text: str) -> str:
        R = ROMAN_RE
        words = "|".join(re.escape(w) for w in (*self.roman_words, *self.chapter_words, *self.part_words))
        if words:
            def chapter(m: re.Match) -> str:
                if m.group(3) == "I" and m.group(1)[0].islower():
                    return m.group(0)  # «in part I thought»
                return m.group(1) + m.group(2) + self.roman_cardinal(roman_to_int(m.group(3)))

            text = re.sub(rf"\b((?i:{words}))(\s+)({R})\b", chapter, text)
        if self.century_before:
            text = re.sub(rf"\b((?i:{'|'.join(self.century_before)}))(\s+)({R})\b",
                          lambda m: m.group(1) + m.group(2) + self.roman_century(roman_to_int(m.group(3))), text)
        if self.century_after:
            text = re.sub(rf"\b({ROMAN_LOOSE})({self.century_suffix})(\s+(?i:{'|'.join(self.century_after)})\b)",
                          lambda m: self.roman_century(roman_to_int(m.group(1)), prev_word(text, m.start()))
                          + m.group(3), text)
        dot = r"(\.(?=\s+[a-zà-ÿ]))?" if self.roman_dot else ""

        def regnal(m: re.Match) -> str:
            num = m.group(3)
            n = roman_to_int(num)
            if num == "I" or (len(num) == 1 and num != "V") or n > 39:
                return m.group(0)
            return f"{m.group(1)}{m.group(2)}{self.roman_regnal(n, m.group(1))}"

        return re.sub(rf"\b([A-ZÀ-ÖØ-Þ][^\W\d_]+)(\s+)({R})\b{dot}", regnal, text)

    def times(self, text: str) -> str:
        def one(m: re.Match) -> str:
            h, mi = int(m.group(1)), int(m.group(2))
            if h > 24 or mi > 59:
                return m.group(0)
            suffix = (m.group(3) or "").lower().replace(".", "")
            if not suffix:
                tok = prev_token(text, m.start())
                if tok[:1].isupper() and tok.lower() not in self.time_preps:
                    return m.group(0)  # «John 3:16»
            return self.time_words(h, mi, suffix if suffix in ("am", "pm") else None)

        return TIME.sub(one, text)

    def money(self, text: str) -> str:
        if not self.currencies:
            return text
        syms = "|".join(re.escape(k) for k in sorted(MONEY_SYMBOLS, key=len, reverse=True))
        scale = f"(?:\\s({'|'.join(self.money_scales)}))?" if self.money_scales else "()"

        def render(key: str, amount: str, sc: str | None) -> str:
            one, many, sub_one, sub_many, fem = self.currencies[key]
            if sc:
                return f"{self.number(amount.replace(' ', ''))} {sc} {many}"
            whole, frac = parse_amount(amount)
            out = f"{self.cardinal_noun(whole, fem)} {one if whole == 1 else many}"
            if frac:
                f = int(frac)
                out += f"{self.money_join}{self.cardinal_noun(f)} {sub_one if f == 1 else sub_many}"
            return out

        text = re.sub(rf"(?<![\w$€£¥])({syms})\s?({AMOUNT}){scale}(?!\d)",
                      lambda m: render(MONEY_SYMBOLS[m.group(1)], m.group(2), m.group(3))
                      if MONEY_SYMBOLS[m.group(1)] in self.currencies else m.group(0), text)
        by_word = {w.lower(): k for k, v in self.currencies.items() for w in v[:2]} if self.currency_words else {}
        alts = [re.escape(k) for k in sorted(MONEY_SYMBOLS, key=len, reverse=True)]
        alts += [re.escape(w) for w in sorted(by_word, key=len, reverse=True)]

        def suffix(m: re.Match) -> str:
            tok = m.group(2)
            key = MONEY_SYMBOLS.get(tok) or MONEY_SYMBOLS.get(tok.upper()) or by_word.get(tok.lower())
            return render(key, m.group(1), None) if key in self.currencies else m.group(0)

        return re.sub(rf"(?<![\w.,])({AMOUNT})\s?({'|'.join(alts)})(?![\w])", suffix, text, flags=re.IGNORECASE)

    def measures(self, text: str) -> str:
        if not self.units:
            return text
        rx = self.__dict__.get("_unit_rx") or self.__dict__.setdefault("_unit_rx", unit_regex(self.units))

        def one(m: re.Match) -> str:
            sing, many = self.units[m.group(3)]
            value = float(m.group(1).replace(",", "."))
            return f"{m.group(1)} {many if self.is_plural(value) else sing}"

        return rx.sub(one, text)

    def agreement(self, text: str) -> str:
        def one(m: re.Match) -> str:
            r = self.agree(int(m.group(1)), m.group(2))
            if r is None:
                return m.group(0)
            return f"{r}{m.group(2)}" if r.endswith("'") else f"{r} {m.group(2)}"

        return re.sub(r"(?<![\w.,])(\d+)\s+([^\W\d_]+)", one, text)


class CJKLanguage(Language):
    cps = (2.5, 10.0)
    chars_per_second = 5.0
    SYMBOLS: dict[str, str] = {}
    units: dict[str, tuple[str, str]] = {}

    def numbers(self, text: str) -> str:
        text = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", text)
        text = phones(text, self.number, self.plus_word)
        text = self.times(text)
        text = self.money(text)
        text = self.measures(text)
        text = self.counters(text)
        for k, v in self.SYMBOLS.items():
            text = text.replace(k, v)
        return self.plain_numbers(text)

    plus_word = "加"

    def plain_numbers(self, text: str) -> str:
        return re.sub(r"(?<![\d.,])\d+(?:\.\d+)?", lambda m: self.number(m.group(0)), text)

    def times(self, text: str) -> str:
        return text

    def money(self, text: str) -> str:
        return text

    def counters(self, text: str) -> str:
        return text

    def measures(self, text: str) -> str:
        if not self.units:
            return text
        rx = self.__dict__.get("_unit_rx") or self.__dict__.setdefault("_unit_rx", unit_regex(self.units, True))
        return rx.sub(lambda m: m.group(1) + self.units[m.group(3)][0], text)

    def sentences(self, text: str) -> list[str]:
        parts = re.split(r"(?<=[。！？!?…])(?![。！？!?…」』”）)])\s*", text)
        return [p.strip() for p in parts if p.strip()]

    def canonical(self, text: str) -> str:
        return super().canonical(text).replace(" ", "")  # CER per character, spaces are not meaningful

    def is_continuation(self, sentence: str) -> bool:
        return False


TIME = re.compile(r"(?<![\w:.,/-])(\d{1,2})[:h](\d{2})(?![\d:]|[.,]\d)"
                  r"(?:\s?(a\.?m\.?|p\.?m\.?|Uhr|heures?|horas?|ore|h)(?!\w))?", re.IGNORECASE)


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
