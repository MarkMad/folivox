from __future__ import annotations

import re

from num2words import num2words

from folivox.lang import LatinLanguage, register
from folivox.lang.rules import parse_units, prev_word

MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")


class English(LatinLanguage):
    code, name, native = "en", "English", "English"
    chapter_label, intro_label = "Chapter {n}", "Introduction"
    part_words = ("part", "book", "volume")
    chapter_words = ("chapter",)
    standalone_words = ("prologue", "epilogue", "introduction", "preface", "foreword", "afterword", "interlude")
    abbreviations = ("mr", "mrs", "ms", "dr", "prof", "st", "jr", "sr", "vs", "etc", "e.g", "i.e", "mt", "no")
    hallucinations = (r"thanks? (?:you )?for watching\W*", r"subtitles? by[^.!?]*[.!?]?")
    SYMBOLS = {"&": " and ", "%": " percent", "$": " dollars ", "+": " plus ", "=": " equals ", "@": " at "}
    thousands_re = r"(?<=\d),(?=\d{3}(?!\d))"
    abbreviation_map = (
        (r"Mr\.", "Mister"), (r"Mrs\.", "Missus"), (r"Ms\.", "Miss"),
        (r"Dr\.(?=\s+[A-Z])", "Doctor"), (r"Prof\.(?=\s+[A-Z])", "Professor"),
        (r"Capt\.(?=\s+[A-Z])", "Captain"), (r"Col\.(?=\s+[A-Z])", "Colonel"),
        (r"Lt\.(?=\s+[A-Z])", "Lieutenant"), (r"Sgt\.(?=\s+[A-Z])", "Sergeant"),
        (r"Rev\.(?=\s+[A-Z])", "Reverend"), (r"Mt\.(?=\s+[A-Z])", "Mount"),
        (r"Jr\.", "Junior"), (r"vs\.", "versus"), (r"e\.g\.", "for example"), (r"i\.e\.", "that is"),
        (r"No\.(?=\s*\d)", "number"),
    )
    months = MONTHS
    roman_words = ("war", "act", "scene", "level", "stage", "phase", "season", "episode", "class", "type",
                   "vol", "section", "article", "appendix", "table", "figure")
    century_after = ("century", "centuries")
    time_preps = ("at", "by", "until", "till", "from", "before", "after", "around", "about", "since", "to",
                  "past", "between", "and", "noon")
    currencies = {
        "usd": ("dollar", "dollars", "cent", "cents", False),
        "eur": ("euro", "euros", "cent", "cents", False),
        "gbp": ("pound", "pounds", "penny", "pence", False),
        "jpy": ("yen", "yen", "sen", "sen", False),
    }
    money_scales = ("million", "billion", "trillion", "thousand")
    units = parse_units("""
        km/h=kilometer per hour|kilometers per hour
        mph=mile per hour|miles per hour
        m/s=meter per second|meters per second
        km²=square kilometer|square kilometers
        m²=square meter|square meters
        cm²=square centimeter|square centimeters
        m³=cubic meter|cubic meters
        km=kilometer|kilometers
        kg=kilogram|kilograms
        mg=milligram|milligrams
        cm=centimeter|centimeters
        mm=millimeter|millimeters
        ml=milliliter|milliliters
        kHz=kilohertz
        MHz=megahertz
        GHz=gigahertz
        Hz=hertz
        kW=kilowatt|kilowatts
        GB=gigabyte|gigabytes
        MB=megabyte|megabytes
        KB=kilobyte|kilobytes
        TB=terabyte|terabytes
        °C=degree Celsius|degrees Celsius
        °F=degree Fahrenheit|degrees Fahrenheit
        °=degree|degrees
        ft=foot|feet
        lb=pound|pounds
        lbs=pound|pounds
        oz=ounce|ounces
        mi=mile|miles
        g=gram|grams
        m=meter|meters
        l=liter|liters
        h=hour|hours
    """)

    def ordinal_word(self, n: int, feminine: bool = False) -> str:
        return num2words(n, lang="en", to="ordinal")

    def roman_regnal(self, n: int, name: str) -> str:
        return "the " + self.ordinal_word(n)

    def roman_century(self, n: int, ctx: str = "") -> str:
        return self.ordinal_word(n)

    def time_words(self, h: int, m: int, meridiem: str | None) -> str:
        hw = self.number(str(h))
        tail = f" {'a' if meridiem == 'am' else 'p'} m" if meridiem else ""
        if m == 0:
            if meridiem:
                return hw + tail
            return f"{hw} o'clock" if 1 <= h <= 12 else f"{hw} hundred"
        mw = self.number(str(m))
        return f"{hw} {'oh ' if m < 10 else ''}{mw}{tail}"

    def dates(self, text: str) -> str:
        mo = "|".join(self.months)

        def month_day(m: re.Match) -> str:
            d = int(m.group(2))
            return f"{m.group(1)} {self.ordinal_word(d)}" if 1 <= d <= 31 else m.group(0)

        def day_month(m: re.Match) -> str:
            d = int(m.group(1))
            if not 1 <= d <= 31:
                return m.group(0)
            the = "" if prev_word(text, m.start()) == "the" else "the "
            return f"{the}{self.ordinal_word(d)} of {m.group(3)}"

        text = re.sub(rf"\b({mo})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?![\d:])", month_day, text)
        return re.sub(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?(\s+(?:of\s+)?)({mo})\b", day_month, text)

    def ordinals(self, text: str) -> str:
        return re.sub(r"\b(\d+)(st|nd|rd|th)\b", lambda m: num2words(int(m.group(1)), lang="en", to="ordinal"),
                      text)


register(English())
