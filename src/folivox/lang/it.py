from __future__ import annotations

import re

from folivox.lang import LatinLanguage, register


class Italian(LatinLanguage):
    code, name, native = "it", "Italian", "Italiano"
    chapter_label, intro_label = "Capitolo {n}", "Introduzione"
    part_words = ("parte", "libro", "volume")
    chapter_words = ("capitolo",)
    standalone_words = ("prologo", "epilogo", "prefazione", "introduzione", "postfazione")
    abbreviations = ("sig", "sigg", "sig.ra", "dott", "prof", "ecc", "pag", "p", "s")
    hallucinations = (r"sottotitoli (?:creati |a cura )?(?:dalla|di|da)[^.!?]*[.!?]?", r"grazie per la visione\W*")
    SYMBOLS = {"&": " e ", "%": " per cento", "€": " euro", "+": " più ", "=": " uguale "}

    def numbers(self, text: str) -> str:
        text = re.sub(r"(\d)\.(\d{3})\b", r"\1\2", text)
        for k, v in self.SYMBOLS.items():
            text = text.replace(k, v)
        return super().numbers(text)


register(Italian())
