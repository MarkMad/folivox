from __future__ import annotations

import re

from num2words import num2words

from folivox.lang import LatinLanguage, register
from folivox.lang.rules import parse_units

FEM_WORDS = {"femme", "fille", "maison", "heure", "année", "fois", "nuit", "personne", "chose", "minute", "seconde",
             "semaine", "vie", "main", "mère", "sœur", "soeur", "ville", "rue", "table", "chambre", "porte",
             "fenêtre", "lettre", "voix", "dent", "tête", "terre", "route", "église", "histoire", "page", "lune",
             "étoile", "vache", "poule", "journée", "soirée", "matinée", "pièce", "phrase", "question", "réponse",
             "idée", "image", "feuille", "fleur", "plante", "pomme", "bouteille", "tasse", "voiture", "bague",
             "clé", "clef", "montre", "carte", "règle", "note", "ligne", "colonne", "case", "boîte", "lampe",
             "chaise", "robe", "jupe", "chemise", "cuillère", "fourchette", "assiette", "pierre", "mort"}
FEM_SUFFIX = ("tion", "sion", "té", "ée", "ette", "ance", "ence", "ure", "ise", "aine", "enne", "esse", "ière",
              "euse", "elle", "ille", "ine", "ade", "ude")
NOT_FEM = {"musée", "lycée", "trophée", "mausolée", "pygmée", "apogée", "mort"}


def is_feminine(word: str) -> bool:
    w = word.lower()
    w = w[:-1] if w.endswith(("s", "x")) and len(w) > 3 else w
    return w not in NOT_FEM and (w in FEM_WORDS or w.endswith(FEM_SUFFIX))


class French(LatinLanguage):
    code, name, native = "fr", "French", "Français"
    chapter_label, intro_label = "Chapitre {n}", "Introduction"
    part_words = ("partie", "livre", "tome")
    chapter_words = ("chapitre",)
    standalone_words = ("prologue", "épilogue", "préface", "avant-propos", "introduction", "postface")
    abbreviations = ("m", "mme", "mlle", "dr", "st", "ste", "etc", "p", "cf", "n°")
    hallucinations = (r"sous-titr\w* (?:par|réalisés)[^.!?]*[.!?]?", r"merci d'avoir regardé\W*")
    SYMBOLS = {"&": " et ", "%": " pour cent", "€": " euros", "+": " plus ", "=": " égale "}
    thousands_re = r"(?<=\d)[   ](?=\d{3}(?!\d))"
    abbreviation_map = (
        (r"M\.(?=\s+[A-ZÉÈ])", "Monsieur"), (r"MM\.", "Messieurs"), (r"Mme\.?", "Madame"),
        (r"Mlle\.?", "Mademoiselle"), (r"Dr\.?(?=\s+[A-ZÉÈ])", "Docteur"), (r"Pr\.(?=\s+[A-ZÉÈ])", "Professeur"),
        (r"St\.(?=\s+[A-ZÉÈ])", "Saint"), (r"Ste\.(?=\s+[A-ZÉÈ])", "Sainte"), (r"cf\.", "voir"),
        (r"[nN]°\s?(?=\d)", "numéro "),
    )
    months = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
              "novembre", "décembre")
    roman_words = ("acte", "scène", "article", "annexe", "tableau", "figure", "fig")
    century_after = ("siècle", "siècles")
    century_suffix = r"(?:e|ème|è|er)?"
    time_preps = ("à", "vers", "avant", "après", "jusqu", "dès", "depuis", "entre", "et", "dès")
    currencies = {
        "usd": ("dollar", "dollars", "cent", "cents", False),
        "eur": ("euro", "euros", "centime", "centimes", False),
        "gbp": ("livre sterling", "livres sterling", "penny", "pence", True),
        "jpy": ("yen", "yens", "sen", "sen", False),
    }
    units = parse_units("""
        km/h=kilomètre par heure|kilomètres par heure
        m/s=mètre par seconde|mètres par seconde
        km²=kilomètre carré|kilomètres carrés
        m²=mètre carré|mètres carrés
        cm²=centimètre carré|centimètres carrés
        m³=mètre cube|mètres cubes
        km=kilomètre|kilomètres
        kg=kilogramme|kilogrammes
        mg=milligramme|milligrammes
        cm=centimètre|centimètres
        mm=millimètre|millimètres
        ml=millilitre|millilitres
        kHz=kilohertz
        MHz=mégahertz
        GHz=gigahertz
        Hz=hertz
        kW=kilowatt|kilowatts
        GB=gigaoctet|gigaoctets
        MB=mégaoctet|mégaoctets
        KB=kilooctet|kilooctets
        TB=téraoctet|téraoctets
        °C=degré Celsius|degrés Celsius
        °F=degré Fahrenheit|degrés Fahrenheit
        °=degré|degrés
        g=gramme|grammes
        m=mètre|mètres
        l=litre|litres
        h=heure|heures
    """)

    def is_plural(self, value: float) -> bool:
        return value >= 2

    def cardinal_noun(self, n: int, feminine: bool = False) -> str:
        words = num2words(n, lang="fr")
        return words + "e" if feminine and words.endswith("un") else words

    def ordinal_word(self, n: int, feminine: bool = False) -> str:
        if n == 1:
            return "première" if feminine else "premier"
        return num2words(n, lang="fr", to="ordinal")

    def roman_cardinal(self, n: int) -> str:
        return "premier" if n == 1 else self.number(str(n))

    def roman_century(self, n: int, ctx: str = "") -> str:
        return self.ordinal_word(n)

    def time_words(self, h: int, m: int, meridiem: str | None) -> str:
        if m == 0 and h in (0, 24):
            return "minuit"
        if m == 0 and h == 12:
            return "midi"
        hw = "une heure" if h == 1 else f"{self.number(str(h))} heures"
        return f"{hw} {self.number(str(m))}" if m else hw

    def dates(self, text: str) -> str:
        mo = "|".join(self.months)

        def numeric(m: re.Match) -> str:
            d, mth = int(m.group(1)), int(m.group(2))
            if not (1 <= d <= 31 and 1 <= mth <= 12):
                return m.group(0)
            return f"{'premier' if d == 1 else d} {self.months[mth - 1]} {m.group(3)}"

        text = re.sub(r"(?<![\d./-])(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})(?!\d)", numeric, text)
        return re.sub(rf"(?<![\d.,])\b1(?=\s+(?i:{mo})\b)", "premier", text)

    def romans(self, text: str) -> str:
        # «François Ier», «Élisabeth Ire»: the bare «I» is skipped as ambiguous, the suffixed form is not
        text = re.sub(r"\b([A-ZÀ-ÖØ-Þ][^\W\d_]+\s+)I(er|re)\b",
                      lambda m: m.group(1) + ("premier" if m.group(2) == "er" else "première"), text)
        return super().romans(text)

    def ordinals(self, text: str) -> str:
        def one(m: re.Match) -> str:
            n, suffix = int(m.group(1)), m.group(2)
            if suffix in ("nd", "nde"):
                return "seconde" if suffix == "nde" else "second"
            return self.ordinal_word(n, suffix in ("re", "ère"))

        return re.sub(r"(?<![\w.,])(\d+)(ère|er|re|ème|è|nde|nd|e)(?![\w])", one, text)

    def agree(self, n: int, word: str) -> str | None:
        if n % 10 != 1 or not is_feminine(word):
            return None
        words = self.cardinal_noun(n, True)
        return words if words != num2words(n, lang="fr") else None


register(French())
