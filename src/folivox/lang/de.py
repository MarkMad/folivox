from __future__ import annotations

import re

from folivox.lang import LatinLanguage, register


class German(LatinLanguage):
    code, name, native = "de", "German", "Deutsch"
    chapter_label, intro_label = "Kapitel {n}", "Einleitung"
    part_words = ("teil", "buch", "band")
    chapter_words = ("kapitel",)
    standalone_words = ("prolog", "epilog", "vorwort", "nachwort", "einleitung")
    abbreviations = ("z.b", "d.h", "u.a", "usw", "bzw", "ca", "dr", "prof", "nr", "str", "vgl", "evtl", "hr", "fr")
    hallucinations = (r"untertitel (?:im auftrag|von)[^.!?]*[.!?]?", r"vielen dank fürs zuschauen\W*")
    SYMBOLS = {"&": " und ", "%": " Prozent", "€": " Euro", "+": " plus ", "=": " gleich "}

    def numbers(self, text: str) -> str:
        text = re.sub(r"(\d)\.(\d{3})\b", r"\1\2", text)  # 10.000 → 10000
        for k, v in self.SYMBOLS.items():
            text = text.replace(k, v)
        return super().numbers(text)


register(German())
