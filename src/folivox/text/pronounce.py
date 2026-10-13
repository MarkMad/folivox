"""Custom pronunciations: a plain-text lexicon that sits next to the book.

    # comment
    Kvothe     = Quothe                 # respelling: works with every engine
    Tolkien*   = Tolkeen                # «*» = any ending, kept: Tolkien's, Tolkiens
    Kvothe     = /K W OW1 TH/ | Quothe  # phonemes for the local engine | respelling for the others
    Фолиокс    = Фол+иокс               # Russian stress: «+» before the vowel, or ´ ' after it, or a capital: ФолИокс

Whatever is typed, stress is normalised to the combining acute (U+0301), the mark CosyVoice 3 reads as
stress. Online engines would read any such mark aloud, so they get the respelling without it.
Quality control compares the recording with the respelled text, never with phoneme markup.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

ACUTE = "́"
RU_VOWELS = "аеёиоуыэюяАЕЁИОУЫЭЮЯ"
_STRESS_AFTER = "'’ʼ´ˊ" + ACUTE  # typed after the stressed vowel
# CMU/ARPAbet symbols CosyVoice 3 has tokens for; vowels take a stress digit 0-2
_VOWELS = {"AA", "AE", "AH", "AO", "AW", "AY", "EH", "ER", "EY", "IH", "IY", "OW", "OY", "UH", "UW"}
_CONSONANTS = {"B", "CH", "D", "DH", "F", "G", "HH", "JH", "K", "L", "M", "N", "NG", "P", "R", "S", "SH", "T", "TH",
               "V", "W", "Y", "Z", "ZH"}
_MARK = ""  # private-use placeholders around substituted text, so replacements never chain
_END = ""
_WORD = r"\w" + ACUTE


class PronounceError(ValueError):
    pass


LATIN_VOWELS = "aeiouyAEIOUY"
_TOKEN = re.compile(rf"[{_WORD}'’ʼ´ˊ+]+")


def _russian_word(w: str) -> str:
    w = re.sub(rf"\+([{RU_VOWELS}])", lambda v: v.group(1) + ACUTE, w)
    w = re.sub(rf"([{RU_VOWELS}])[{re.escape(_STRESS_AFTER)}]", lambda v: v.group(1) + ACUTE, w)
    if ACUTE not in w:  # a single capital vowel inside a lowercase word: замОк
        caps = [i for i, c in enumerate(w) if i and c in RU_VOWELS and c.isupper()]
        if len(caps) == 1 and w[1:].replace(w[caps[0]], "").islower():
            i = caps[0]
            w = w[:i] + w[i].lower() + ACUTE + w[i + 1:]
    return w.replace("ё" + ACUTE, "ё").replace("Ё" + ACUTE, "Ё")


def _latin_word(w: str) -> str:
    """The form CosyVoice 3 follows in English names: an apostrophe right after the stressed vowel (``Mi'randel``)."""
    w = re.sub(rf"\+([{LATIN_VOWELS}])", r"\1'", w)
    w = re.sub(rf"([{LATIN_VOWELS}])[´ˊ{ACUTE}]", r"\1'", w)
    return re.sub(rf"([{LATIN_VOWELS}])[’ʼ](?=[^\W\d_])", r"\1'", w)


def normalize_stress(text: str) -> str:
    """Every accepted way of marking stress → the form the local model follows.

    ``+`` before the stressed vowel, or ``'`` ``´`` after it. In a word with Cyrillic letters the result is a
    combining acute after the vowel (``зам+ок``, ``замо'к``, ``замОк`` → ``замо́к``; one capital vowel also works);
    in a Latin word it is an apostrophe after the vowel (``Mir+andel``, ``Mira´ndel`` → ``Mira'ndel``).
    """
    def word(m: re.Match) -> str:
        w = m.group(0)
        if re.search("[а-яёА-ЯЁ]", w):
            return _russian_word(w)
        return _latin_word(w) if re.search("[A-Za-z]", w) else w

    return _TOKEN.sub(word, text)


def strip_stress(text: str) -> str:
    """The same words without any stress mark, for engines that read marks aloud and for quality control."""
    text = normalize_stress(text).replace(ACUTE, "")
    return re.sub(rf"(?<=[{LATIN_VOWELS}])'(?=[^\W\d_])", "", text)


def parse_phonemes(spec: str) -> str:
    """``K W OW1 TH`` → ``[K][W][OW1][TH]``; raises PronounceError for a symbol the model does not know."""
    out = []
    for sym in spec.upper().replace("[", " ").replace("]", " ").split():
        base = sym.rstrip("012")
        digit = sym[len(base):]
        if base in _VOWELS and len(digit) <= 1 or base in _CONSONANTS and not digit:
            out.append(f"[{sym}]")
        else:
            raise PronounceError(f"unknown phoneme «{sym}» (use CMU/ARPAbet: K W OW1 TH, vowels take 0, 1 or 2)")
    if not out:
        raise PronounceError("empty phoneme list")
    return "".join(out)


@dataclass
class Entry:
    word: str
    pattern: re.Pattern
    wildcard: bool
    rich: str  # what the local model is given: phonemes or a respelling, stress marks allowed
    plain: str | None  # the respelling for the other engines and quality control; None → phonemes only
    phonemes: bool
    line: int
    order: int = 0  # position in the file (the entries are matched longest first, but listed in file order)


@dataclass
class Lexicon:
    entries: list[Entry] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.entries)

    # ---------------------------------------------------------------- reading

    @classmethod
    def load(cls, paths) -> Lexicon:
        """Read the files in order; a later file (the book's own) overrides an earlier one (the series')."""
        lex = cls()
        merged: dict[str, Entry] = {}
        for path in paths:
            path = Path(path)
            try:
                text = path.read_text(encoding="utf-8-sig")
            except OSError as e:
                lex.warnings.append(f"{path.name}: cannot read ({e.strerror or e})")
                continue
            for entry, key, problem in cls._parse(text, path.name):
                if problem:
                    lex.warnings.append(problem)
                elif entry:
                    merged[key] = entry
        for i, e in enumerate(merged.values()):
            e.order = i
        lex.entries = sorted(merged.values(), key=lambda e: -len(e.word))  # longest first
        return lex

    @staticmethod
    def _parse(text: str, name: str):
        for n, raw in enumerate(text.splitlines(), 1):
            line = re.sub(r"(^|\s)#.*$", "", raw).strip()
            if not line:
                continue
            m = re.match(r"^(.*?)\s*(?:=>|->|=|\t)\s*(.*)$", line)
            if not m or not m.group(1) or not m.group(2):
                yield None, "", f"{name}:{n}: expected «word = how to read it», got «{raw.strip()[:40]}»"
                continue
            word, value = m.group(1).strip(), m.group(2).strip()
            try:
                entry = Lexicon._entry(word, value, n)
            except PronounceError as e:
                yield None, "", f"{name}:{n}: {e}"
                continue
            yield entry, word.lower(), None

    @staticmethod
    def _entry(word: str, value: str, line: int) -> Entry:
        wildcard = word.endswith("*")
        stem = word.rstrip("*").strip()
        if not stem:
            raise PronounceError("nothing before «*»")
        rich, _, other = (p.strip() for p in value.partition("|"))
        phonemes = rich.startswith("/") and rich.endswith("/") and len(rich) > 2
        if phonemes:
            rich = parse_phonemes(rich[1:-1])
        elif rich.startswith("/"):
            raise PronounceError("phonemes need a closing «/»")
        plain = other or (None if phonemes else rich)
        body = (r"(?:" + ACUTE + r")?").join(re.escape(c) for c in stem if c != ACUTE)
        pattern = re.compile(rf"(?<![{_WORD}])({body})" + (rf"([{_WORD}]*)" if wildcard else rf"(?![{_WORD}])"),
                             re.IGNORECASE)
        return Entry(word, pattern, wildcard, rich, plain, phonemes, line)

    # ---------------------------------------------------------------- applying

    def apply(self, text: str, *, local: bool = True, quality_control: bool = False) -> str:
        """Substitute the entries in ``text``.

        ``local``: the engine takes stress marks and phonemes. ``quality_control``: the text the recording is
        compared with, so no markup at all and phonemes are replaced by their respelling (or left as written).
        """
        if not self.entries or not text:
            return text
        text = text.replace(_MARK, "").replace(_END, "")
        done: list[str] = []

        def put(value: str) -> str:
            done.append(value)
            return f"{_MARK}{len(done) - 1}{_END}"

        for e in self.entries:
            def sub(m: re.Match, e=e) -> str:
                if quality_control:
                    value = strip_stress(e.plain) if e.plain else m.group(1)
                elif local:
                    value = e.rich if e.phonemes else normalize_stress(e.rich)
                elif e.plain is not None:
                    value = strip_stress(e.plain)
                else:
                    return m.group(0)  # phonemes on an online engine and no respelling given: leave the word
                value = _match_case(m.group(1), value)
                return put(value + (m.group(2) if e.wildcard else ""))

            text = e.pattern.sub(sub, text)
        return re.sub(rf"{_MARK}(\d+){_END}", lambda m: done[int(m.group(1))], text)

    def sample(self, paragraphs: list[str], split, limit: int = 350, longest: int = 220,
               most: int = 4) -> tuple[str, list[str]]:
        """A few sentences of the book to listen to, for the first ``most`` entries in file order: the first
        sentence that contains the entry (``split``: text → sentences). Returns the text and the words the book
        never uses, which are then read on their own."""
        picked: list[str] = []
        missing: list[str] = []
        for e in sorted(self.entries, key=lambda e: e.order)[:most]:
            if any(e.pattern.search(sentence) for sentence in picked):
                continue
            if sum(map(len, picked)) >= limit:
                break
            for text in paragraphs:
                if not e.pattern.search(text):
                    continue
                hit = next((x.strip() for x in split(text) if e.pattern.search(x) and len(x) <= longest), None)
                if hit:
                    picked.append(hit)
                    break
            else:
                missing.append(e.word.rstrip("*"))
                picked.append(f"{e.word.rstrip('*')}.")
        return " ".join(picked), missing

    def unusable_here(self, local: bool) -> list[str]:
        """Entries that cannot be used with this engine (phonemes only, an online engine)."""
        if local:
            return []
        return [e.word for e in self.entries if e.plain is None]


def _match_case(original: str, value: str) -> str:
    if value.startswith("["):  # phonemes
        return value
    if len(original) > 1 and original.isupper():
        return value.upper()
    if original[:1].isupper() and value[:1].islower():
        return value[:1].upper() + value[1:]
    return value


def find(book_path: Path) -> list[Path]:
    """The lexicon files that belong to a book: ``pronounce.txt`` of the folder (a series), then
    ``<book>.pronounce.txt`` (the book itself, which wins)."""
    book_path = Path(book_path)
    cands = [book_path.with_name("pronounce.txt"), book_path.with_name(book_path.stem + ".pronounce.txt")]
    return [p for p in cands if p.is_file()]
