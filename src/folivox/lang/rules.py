"""Small language-independent helpers for the per-language normalisers (romans, amounts, unit tables)."""

from __future__ import annotations

import re

ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
_BODY = r"(?:M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3}))"
ROMAN_RE = r"(?=[MDCLXVI]+\b)" + _BODY  # a whole word of roman letters
ROMAN_LOOSE = r"(?=[MDCLXVI])" + _BODY  # may be followed by an ordinal suffix («XXe»)

# a money amount: «5», «5.50», «5,50», «1,000.50», «1.000,50», «10 000»
AMOUNT = r"\d{1,3}(?:[,.   ]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"
MONEY_SYMBOLS = {"$": "usd", "US$": "usd", "€": "eur", "£": "gbp", "¥": "jpy",
                 "USD": "usd", "EUR": "eur", "GBP": "gbp", "JPY": "jpy"}


def roman_to_int(s: str) -> int:
    total, prev = 0, 0
    for ch in reversed(s.upper()):
        v = ROMAN[ch]
        total = total - v if v < prev else total + v
        prev = max(prev, v)
    return total


def parse_amount(s: str) -> tuple[int, str | None]:
    """«1.000,50» → (1000, "50"); «5.5» → (5, "50"); «1,000» → (1000, None)."""
    s = re.sub(r"[   ]", "", s)
    frac = None
    m = re.search(r"[.,](\d{1,2})$", s)
    if m:
        frac = m.group(1).ljust(2, "0")
        s = s[: m.start()]
    return int(re.sub(r"[.,]", "", s)), (None if frac == "00" else frac)


def parse_units(spec: str) -> dict[str, tuple[str, str]]:
    """«kg=kilogram|kilograms» lines → {"kg": ("kilogram", "kilograms")}; one form means invariable."""
    out: dict[str, tuple[str, str]] = {}
    for line in spec.strip().splitlines():
        key, _, names = line.strip().partition("=")
        one, _, many = names.partition("|")
        out[key.strip()] = (one.strip(), (many or one).strip())
    return out


def prev_word(text: str, pos: int) -> str:
    """The lowercase word right before ``pos`` (apostrophes and trailing spaces skipped)."""
    m = re.search(r"([^\W\d_]+)[’']?\s*$", text[:pos])
    return m.group(1).lower() if m else ""


def prev_token(text: str, pos: int) -> str:
    m = re.search(r"([^\W\d_]+)[’']?\s*$", text[:pos])
    return m.group(1) if m else ""


def digits_spoken(number, s: str) -> str:
    """«600 123» → each digit through ``number`` (a phone number is not a cardinal)."""
    return " ".join(number(d) for d in s if d.isdigit())


PHONE = re.compile(r"(?<![\w+])\+\d[\d\s().\-]{6,}\d(?!\w)")


def phones(text: str, number, plus: str = "plus") -> str:
    def one(m: re.Match) -> str:
        return f"{plus} {digits_spoken(number, m.group(0))}"

    return PHONE.sub(one, text)


def unit_regex(units: dict[str, tuple[str, str]], cjk: bool = False) -> re.Pattern:
    keys = "|".join(re.escape(k) for k in sorted(units, key=len, reverse=True))
    if cjk:  # no word boundaries around CJK text
        return re.compile(rf"(?<![\d.,])(\d+(?:[.,]\d+)?)(\s?)({keys})(?![A-Za-z²³/])")
    return re.compile(rf"(?<![\w.,])(\d+(?:[.,]\d+)?)(\s?)({keys})(?![\w²³/])")


def ko_native(n: int, determiner: bool = True) -> str | None:
    """Native Korean numeral before a counter (1–99): 한, 두, 세, 네 … 스무, 스물한. None above 99."""
    if not 1 <= n <= 99:
        return None
    tens = ["", "열", "스물", "서른", "마흔", "쉰", "예순", "일흔", "여든", "아흔"]
    ones = ["", "한", "두", "세", "네", "다섯", "여섯", "일곱", "여덟", "아홉"]
    t, o = divmod(n, 10)
    if n == 20 and determiner:
        return "스무"
    return tens[t] + ones[o]
