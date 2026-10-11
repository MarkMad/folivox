from __future__ import annotations

import re

from num2words import num2words

from folivox.lang import LatinLanguage, register
from folivox.lang.rules import parse_units

STOP = {"di", "e", "a", "da", "in", "con", "su", "per", "tra", "fra", "che", "è", "o", "ma", "se", "il", "la", "lo",
        "le", "un", "una", "uno", "i", "gli", "non", "mi", "ti", "si", "ci", "come", "ed", "ad", "al", "del", "nel"}
MASC_A = {"problema", "programma", "sistema", "tema", "cinema", "poeta", "pianeta", "clima", "dramma", "panorama",
          "diploma", "teorema", "schema", "telegramma", "diagramma", "pigiama", "papa", "profeta", "turista"}
FEM_OTHER = {"notte", "madre", "parte", "gente", "chiave", "legge", "mente", "morte", "sorte", "fine", "sera",
             "cosa", "mano", "foto", "moto", "radio", "volte"}
FEM_END = ("ione", "tà", "tù", "trice", "udine")


def is_feminine(word: str) -> bool:
    w = word.lower()
    if w in MASC_A:
        return False
    return w.endswith("a") or w in FEM_OTHER or w.endswith(FEM_END)


class Italian(LatinLanguage):
    code, name, native = "it", "Italian", "Italiano"
    chapter_label, intro_label = "Capitolo {n}", "Introduzione"
    part_words = ("parte", "libro", "volume")
    chapter_words = ("capitolo",)
    standalone_words = ("prologo", "epilogo", "prefazione", "introduzione", "postfazione")
    abbreviations = ("sig", "sigg", "sig.ra", "dott", "prof", "ecc", "pag", "p", "s")
    hallucinations = (r"sottotitoli (?:creati |a cura )?(?:dalla|di|da)[^.!?]*[.!?]?", r"grazie per la visione\W*")
    SYMBOLS = {"&": " e ", "%": " per cento", "€": " euro", "+": " più ", "=": " uguale "}
    thousands_re = r"(?<=\d)\.(?=\d{3}(?!\d))"
    abbreviation_map = (
        (r"[Ss]ig\.ra", "signora"), (r"[Ss]ig\.(?=\s+[A-Z])", "signor"), (r"[Ss]igg\.", "signori"),
        (r"[Dd]ott\.ssa", "dottoressa"), (r"[Dd]ott\.(?=\s+[A-Z])", "dottor"), (r"[Pp]rof\.(?=\s+[A-Z])", "professor"),
        (r"[Aa]vv\.(?=\s+[A-Z])", "avvocato"), (r"[Ii]ng\.(?=\s+[A-Z])", "ingegner"), (r"pagg\.", "pagine"),
        (r"pag\.", "pagina"), (r"cfr\.", "confronta"), (r"[nN]\.\s?(?=\d)", "numero "),
    )
    months = ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre",
              "ottobre", "novembre", "dicembre")
    roman_words = ("atto", "scena", "articolo", "appendice", "tabella", "figura", "fig")
    century_after = ("secolo", "secoli")
    fem_names = ("Elisabetta", "Maria", "Caterina", "Vittoria", "Anna", "Giovanna", "Margherita", "Isabella")
    time_preps = ("alle", "ore", "le", "verso", "dalle", "fino", "dopo", "prima", "circa", "e", "tra", "fra")
    currencies = {
        "usd": ("dollaro", "dollari", "centesimo", "centesimi", False),
        "eur": ("euro", "euro", "centesimo", "centesimi", False),
        "gbp": ("sterlina", "sterline", "penny", "penny", True),
        "jpy": ("yen", "yen", "sen", "sen", False),
    }
    money_join = " e "
    units = parse_units("""
        km/h=chilometro orario|chilometri orari
        m/s=metro al secondo|metri al secondo
        km²=chilometro quadrato|chilometri quadrati
        m²=metro quadrato|metri quadrati
        cm²=centimetro quadrato|centimetri quadrati
        m³=metro cubo|metri cubi
        km=chilometro|chilometri
        kg=chilogrammo|chilogrammi
        mg=milligrammo|milligrammi
        cm=centimetro|centimetri
        mm=millimetro|millimetri
        ml=millilitro|millilitri
        kHz=chilohertz
        MHz=megahertz
        GHz=gigahertz
        Hz=hertz
        kW=chilowatt
        GB=gigabyte
        MB=megabyte
        KB=kilobyte
        TB=terabyte
        °C=grado Celsius|gradi Celsius
        °F=grado Fahrenheit|gradi Fahrenheit
        °=grado|gradi
        g=grammo|grammi
        m=metro|metri
        l=litro|litri
        h=ora|ore
    """)

    def cardinal_noun(self, n: int, feminine: bool = False) -> str:
        if n == 1:
            return "una" if feminine else "un"
        return num2words(n, lang="it")

    def ordinal_word(self, n: int, feminine: bool = False) -> str:
        w = num2words(n, lang="it", to="ordinal")
        return w[:-1] + "a" if feminine and w.endswith("o") else w

    def roman_cardinal(self, n: int) -> str:
        return "primo" if n == 1 else self.number(str(n))

    def roman_regnal(self, n: int, name: str) -> str:
        return self.ordinal_word(n, name in self.fem_names)

    def roman_century(self, n: int, ctx: str = "") -> str:
        return self.ordinal_word(n)

    def time_words(self, h: int, m: int, meridiem: str | None) -> str:
        hw = "una" if h == 1 else self.number(str(h))
        return f"{hw} e {self.number(str(m))}" if m else hw

    def dates(self, text: str) -> str:
        mo = "|".join(self.months)

        def numeric(m: re.Match) -> str:
            d, mth = int(m.group(1)), int(m.group(2))
            if not (1 <= d <= 31 and 1 <= mth <= 12):
                return m.group(0)
            return f"{'primo' if d == 1 else d} {self.months[mth - 1]} {m.group(3)}"

        text = re.sub(r"(?<![\d./-])(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})(?!\d)", numeric, text)
        return re.sub(rf"(?<![\d.,])\b1(?=\s+(?i:{mo})\b)", "primo", text)

    def ordinals(self, text: str) -> str:
        return re.sub(r"(?<![\w.,])(\d+)([ºª°])(?![\w])(?!\s*[CF]\b)",
                      lambda m: self.ordinal_word(int(m.group(1)), m.group(2) == "ª"), text)

    def agree(self, n: int, word: str) -> str | None:
        w = word.lower()
        if n != 1 or len(w) < 3 or w in STOP:
            return None
        if is_feminine(w):
            return "un'" if w[0] in "aeiouàèéìòù" else "una"
        return "uno" if re.match(r"(z|gn|ps|x|y|s[^aeiou\W\d])", w) else "un"


register(Italian())
