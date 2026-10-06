from __future__ import annotations

import re

from num2words import num2words

from folivox.lang import LatinLanguage, register


class English(LatinLanguage):
    code, name, native = "en", "English", "English"
    chapter_label, intro_label = "Chapter {n}", "Introduction"
    part_words = ("part", "book", "volume")
    chapter_words = ("chapter",)
    standalone_words = ("prologue", "epilogue", "introduction", "preface", "foreword", "afterword", "interlude")
    abbreviations = ("mr", "mrs", "ms", "dr", "prof", "st", "jr", "sr", "vs", "etc", "e.g", "i.e", "mt", "no")
    hallucinations = (r"thanks? (?:you )?for watching\W*", r"subtitles? by[^.!?]*[.!?]?")
    SYMBOLS = {"&": " and ", "%": " percent", "$": " dollars ", "+": " plus ", "=": " equals ", "@": " at "}

    def numbers(self, text: str) -> str:
        text = re.sub(r"\b(\d+)(st|nd|rd|th)\b", lambda m: num2words(int(m.group(1)), lang="en", to="ordinal"),
                      text)
        text = re.sub(r"\$(\d+(?:\.\d+)?)", r"\1 dollars", text)
        text = re.sub(r"(\d),(\d{3})\b", r"\1\2", text)  # 10,000 → 10000
        for k, v in self.SYMBOLS.items():
            text = text.replace(k, v)
        return super().numbers(text)


register(English())
