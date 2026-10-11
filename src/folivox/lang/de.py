from __future__ import annotations

import re

from num2words import num2words

from folivox.lang import LatinLanguage, register
from folivox.lang.rules import parse_units, prev_word

# prepositions and articles that put the following ordinal into the dative/accusative/genitive («am dritten Mai»)
N_CASE = {"am", "vom", "zum", "bis", "seit", "ab", "im", "dem", "den", "des", "vor", "nach", "auf", "für", "von",
          "zu", "an", "um", "mit", "bei", "aus", "in", "gegen", "ins", "zur", "beim", "ersten", "letzten"}
STOP_CAPS = {"Und", "Oder", "Aber", "Dann", "Der", "Die", "Das", "Er", "Sie", "Es", "Ich", "Wir", "Ihr", "Wenn",
             "Als", "Doch", "Nun", "So", "Da", "Denn", "Auch", "Mal"}
FEM_SUFFIX = ("ung", "heit", "keit", "schaft", "ion", "tät", "ur", "ik", "ie", "ei", "enz", "anz", "erin", "ssin")
FEM_WORDS = {"Frau", "Stunde", "Minute", "Woche", "Nacht", "Stadt", "Hand", "Tür", "Sache", "Zeit", "Straße",
             "Seite", "Mutter", "Tochter", "Schwester", "Katze", "Sekunde", "Million", "Milliarde", "Mark", "Uhr!"}
NOT_FEM_E = {"Junge", "Name", "Gedanke", "Kollege", "Neffe", "Löwe", "Hase", "Affe", "Franzose", "Experte", "Kunde",
             "Bote", "Riese", "Buchstabe", "Glaube", "Friede", "Wille", "Käse", "Ende", "Auge", "Ohre", "Gebäude",
             "Interesse", "Erbe", "Zeuge", "Neue", "Rabe", "Gefährte"}


def is_feminine(word: str) -> bool:
    if word in FEM_WORDS:
        return True
    if word.startswith("Ge") and word.endswith("e"):
        return False
    return word.endswith(FEM_SUFFIX) or (word.endswith("e") and word not in NOT_FEM_E)


class German(LatinLanguage):
    code, name, native = "de", "German", "Deutsch"
    chapter_label, intro_label = "Kapitel {n}", "Einleitung"
    part_words = ("teil", "buch", "band")
    chapter_words = ("kapitel",)
    standalone_words = ("prolog", "epilog", "vorwort", "nachwort", "einleitung")
    abbreviations = ("z.b", "d.h", "u.a", "usw", "bzw", "ca", "dr", "prof", "nr", "str", "vgl", "evtl", "hr", "fr")
    hallucinations = (r"untertitel (?:im auftrag|von)[^.!?]*[.!?]?", r"vielen dank fürs zuschauen\W*")
    SYMBOLS = {"&": " und ", "%": " Prozent", "€": " Euro", "+": " plus ", "=": " gleich "}
    thousands_re = r"(?<=\d)\.(?=\d{3}(?!\d))"
    abbreviation_map = (
        (r"z\.\s?B\.", "zum Beispiel"), (r"d\.\s?h\.", "das heißt"), (r"u\.\s?a\.", "unter anderem"),
        (r"z\.\s?T\.", "zum Teil"), (r"u\.\s?U\.", "unter Umständen"), (r"ggf\.", "gegebenenfalls"),
        (r"bzw\.", "beziehungsweise"), (r"ca\.", "circa"), (r"evtl\.", "eventuell"), (r"vgl\.", "vergleiche"),
        (r"Dr\.(?=\s+[A-ZÄÖÜ])", "Doktor"), (r"Prof\.(?=\s+[A-ZÄÖÜ])", "Professor"),
        (r"Nr\.(?=\s*\d)", "Nummer"), (r"Hr\.(?=\s+[A-ZÄÖÜ])", "Herr"), (r"Fr\.(?=\s+[A-ZÄÖÜ])", "Frau"),
        (r"Jh\.", "Jahrhundert"),
    )
    months = ("Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
              "November", "Dezember")
    roman_words = ("akt", "szene", "abschnitt", "artikel", "anhang", "tabelle", "abbildung", "abb")
    century_after = ("Jahrhundert", "Jahrhunderts", "Jahrhunderte", "Jahrhunderten")
    century_suffix = r"\.?"
    roman_dot = True
    time_preps = ("um", "gegen", "bis", "ab", "von", "seit", "nach", "vor", "ca", "gegen", "zwischen", "und")
    currencies = {
        "usd": ("Dollar", "Dollar", "Cent", "Cent", False),
        "eur": ("Euro", "Euro", "Cent", "Cent", False),
        "gbp": ("Pfund", "Pfund", "Penny", "Pence", False),
        "jpy": ("Yen", "Yen", "Sen", "Sen", False),
    }
    units = parse_units("""
        km/h=Kilometer pro Stunde
        m/s=Meter pro Sekunde
        km²=Quadratkilometer
        m²=Quadratmeter
        cm²=Quadratzentimeter
        m³=Kubikmeter
        km=Kilometer
        kg=Kilogramm
        mg=Milligramm
        cm=Zentimeter
        mm=Millimeter
        ml=Milliliter
        kHz=Kilohertz
        MHz=Megahertz
        GHz=Gigahertz
        Hz=Hertz
        kW=Kilowatt
        GB=Gigabyte
        MB=Megabyte
        KB=Kilobyte
        TB=Terabyte
        °C=Grad Celsius
        °F=Grad Fahrenheit
        °=Grad
        g=Gramm
        m=Meter
        l=Liter
        h=Stunde|Stunden
    """)

    def cardinal_noun(self, n: int, feminine: bool = False) -> str:
        words = num2words(n, lang="de")
        if words.endswith("eins"):
            words = words[:-1] + ("e" if feminine else "")
        return words

    def _ordinal(self, n: int, prev: str, cap: bool = False) -> str:
        w = num2words(n, lang="de", to="ordinal")
        w = w.rstrip("n") if w.endswith("n") else w
        w = w + ("n" if prev in N_CASE else "")
        return w.capitalize() if cap else w

    def roman_regnal(self, n: int, name: str) -> str:
        return "der " + num2words(n, lang="de", to="ordinal").capitalize()

    def roman_century(self, n: int, ctx: str = "") -> str:
        return self._ordinal(n, ctx)

    def time_words(self, h: int, m: int, meridiem: str | None) -> str:
        hw = "ein" if h == 1 else self.number(str(h))
        return f"{hw} Uhr {self.number(str(m))}" if m else f"{hw} Uhr"

    def dates(self, text: str) -> str:
        mo = "|".join(self.months)

        def day_month(m: re.Match) -> str:
            d = int(m.group(1))
            if not 1 <= d <= 31:
                return m.group(0)
            return f"{self._ordinal(d, prev_word(text, m.start()))} {m.group(2)}"

        def numeric(m: re.Match) -> str:
            d, mth = int(m.group(1)), int(m.group(2))
            if not (1 <= d <= 31 and 1 <= mth <= 12):
                return m.group(0)
            return f"{self._ordinal(d, prev_word(text, m.start()))} {self.months[mth - 1]} {m.group(3)}"

        text = re.sub(r"(?<![\d.])(\d{1,2})\.(\d{1,2})\.(\d{4})(?!\d)", numeric, text)
        return re.sub(rf"(?<![\d.])(\d{{1,2}})\.\s+((?i:{mo}))\b", day_month, text)

    def agree(self, n: int, word: str) -> str | None:
        if n != 1 or not word[:1].isupper() or word in STOP_CAPS:
            return None
        return self.cardinal_noun(1, is_feminine(word))


register(German())
