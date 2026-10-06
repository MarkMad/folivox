from __future__ import annotations

import re

from folivox.lang import LatinLanguage, register


class Spanish(LatinLanguage):
    code, name, native = "es", "Spanish", "Español"
    part_words = ("parte", "libro", "tomo")
    chapter_words = ("capítulo", "capitulo")
    standalone_words = ("prólogo", "epílogo", "prefacio", "introducción", "nota del autor")
    abbreviations = ("sr", "sra", "srta", "dr", "dra", "d", "dña", "etc", "ud", "uds", "pág")
    hallucinations = (r"subtítulos (?:realizados )?por[^.!?]*[.!?]?", r"gracias por ver\W*")
    SYMBOLS = {"&": " y ", "%": " por ciento", "€": " euros", "+": " más ", "=": " igual a "}

    def numbers(self, text: str) -> str:
        text = re.sub(r"(\d)\.(\d{3})\b", r"\1\2", text)
        for k, v in self.SYMBOLS.items():
            text = text.replace(k, v)
        return super().numbers(text)


register(Spanish())
