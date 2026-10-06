from __future__ import annotations

import re

from folivox.lang import LatinLanguage, register


class French(LatinLanguage):
    code, name, native = "fr", "French", "Français"
    chapter_label, intro_label = "Chapitre {n}", "Introduction"
    part_words = ("partie", "livre", "tome")
    chapter_words = ("chapitre",)
    standalone_words = ("prologue", "épilogue", "préface", "avant-propos", "introduction", "postface")
    abbreviations = ("m", "mme", "mlle", "dr", "st", "ste", "etc", "p", "cf", "n°")
    hallucinations = (r"sous-titr\w* (?:par|réalisés)[^.!?]*[.!?]?", r"merci d'avoir regardé\W*")
    SYMBOLS = {"&": " et ", "%": " pour cent", "€": " euros", "+": " plus ", "=": " égale "}

    def numbers(self, text: str) -> str:
        text = re.sub(r"(\d)[   ](\d{3})\b", r"\1\2", text)  # 10 000 → 10000
        for k, v in self.SYMBOLS.items():
            text = text.replace(k, v)
        return super().numbers(text)


register(French())
