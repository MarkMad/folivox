from __future__ import annotations

import re

from num2words import num2words

from folivox.lang import LatinLanguage, register
from folivox.lang.rules import parse_units

MASC_A = {"día", "mapa", "planeta", "problema", "sistema", "tema", "idioma", "programa", "poema", "clima", "drama",
          "cura", "papa", "tranvía", "guardia", "colega", "turista", "artista", "pijama", "diploma", "panorama",
          "esquema", "teorema", "diagrama", "telegrama", "enigma", "fantasma", "aroma", "cometa", "profeta"}
FEM_OTHER = {"noche", "calle", "clase", "parte", "serie", "especie", "llave", "nube", "fuente", "gente", "tarde",
             "carne", "sangre", "muerte", "suerte", "mente", "madre", "flor", "voz", "luz", "paz", "vez", "cruz",
             "mujer", "mano", "foto", "moto", "radio", "razón", "canción", "imagen", "orden", "sal", "miel", "piel"}
FEM_END = ("ción", "sión", "dad", "tud", "umbre")
STOP_ONE = {"de", "del", "y", "e", "o", "u", "a", "al", "en", "que", "con", "por", "para", "fue", "es", "era", "se",
            "lo", "la", "el", "un", "una", "mil", "millón", "no", "si", "sí", "pero", "como", "cuando", "ya", "más"}
STOP_PL = {"es", "las", "los", "dos", "tres", "más", "mas", "pues", "les", "nos", "sus", "mis", "tus", "entonces",
           "después", "antes", "además", "jamás", "mientras", "apenas", "luego", "otros", "unos", "estos", "esos"}


def is_feminine(word: str) -> bool:
    w = word.lower()
    for cand in (w, w.removesuffix("s"), w.removesuffix("es")):
        if cand in MASC_A:
            return False
        if cand in FEM_OTHER or cand.endswith(FEM_END) or (cand.endswith("a") and cand != w) or w.endswith("a"):
            return True
    return w.endswith(("dades", "tudes", "umbres", "ciones", "siones")) or (w.endswith("as") and w[:-1] not in MASC_A)


class Spanish(LatinLanguage):
    code, name, native = "es", "Spanish", "Español"
    chapter_label, intro_label = "Capítulo {n}", "Introducción"
    part_words = ("parte", "libro", "tomo")
    chapter_words = ("capítulo", "capitulo")
    standalone_words = ("prólogo", "epílogo", "prefacio", "introducción", "nota del autor")
    abbreviations = ("sr", "sra", "srta", "dr", "dra", "d", "dña", "etc", "ud", "uds", "pág")
    hallucinations = (r"subtítulos (?:realizados )?por[^.!?]*[.!?]?", r"gracias por ver\W*")
    SYMBOLS = {"&": " y ", "%": " por ciento", "€": " euros", "+": " más ", "=": " igual a "}
    thousands_re = r"(?<=\d)\.(?=\d{3}(?!\d))"
    abbreviation_map = (
        (r"Sr\.(?=\s+[A-ZÁÉÍÓÚÑ])", "señor"), (r"Sra\.(?=\s+[A-ZÁÉÍÓÚÑ])", "señora"),
        (r"Srta\.(?=\s+[A-ZÁÉÍÓÚÑ])", "señorita"), (r"Dr\.(?=\s+[A-ZÁÉÍÓÚÑ])", "doctor"),
        (r"Dra\.(?=\s+[A-ZÁÉÍÓÚÑ])", "doctora"), (r"D\.(?=\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ])", "don"),
        (r"Dña\.", "doña"), (r"Ud\.", "usted"), (r"Uds\.", "ustedes"), (r"págs\.", "páginas"),
        (r"pág\.", "página"), (r"p\.\s?ej\.", "por ejemplo"), (r"EE\.\s?UU\.", "Estados Unidos"),
        (r"núm\.(?=\s*\d)", "número"), (r"aprox\.", "aproximadamente"), (r"Prof\.(?=\s+[A-ZÁÉÍÓÚÑ])", "profesor"),
    )
    months = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
              "noviembre", "diciembre")
    roman_words = ("acto", "escena", "artículo", "apéndice", "tabla", "figura", "fig")
    century_before = ("siglo", "siglos")
    fem_names = ("Isabel", "María", "Catalina", "Victoria", "Ana", "Juana", "Carlota", "Margarita", "Sofía",
                 "Cristina", "Elena", "Leonor", "Urraca", "Berenguela")
    time_preps = ("a", "las", "la", "hacia", "desde", "hasta", "antes", "después", "sobre", "y", "entre")
    currencies = {
        "usd": ("dólar", "dólares", "centavo", "centavos", False),
        "eur": ("euro", "euros", "céntimo", "céntimos", False),
        "gbp": ("libra", "libras", "penique", "peniques", True),
        "jpy": ("yen", "yenes", "sen", "sen", False),
    }
    money_join = " con "
    units = parse_units("""
        km/h=kilómetro por hora|kilómetros por hora
        m/s=metro por segundo|metros por segundo
        km²=kilómetro cuadrado|kilómetros cuadrados
        m²=metro cuadrado|metros cuadrados
        cm²=centímetro cuadrado|centímetros cuadrados
        m³=metro cúbico|metros cúbicos
        km=kilómetro|kilómetros
        kg=kilogramo|kilogramos
        mg=miligramo|miligramos
        cm=centímetro|centímetros
        mm=milímetro|milímetros
        ml=mililitro|mililitros
        kHz=kilohercio|kilohercios
        MHz=megahercio|megahercios
        GHz=gigahercio|gigahercios
        Hz=hercio|hercios
        kW=kilovatio|kilovatios
        GB=gigabyte|gigabytes
        MB=megabyte|megabytes
        KB=kilobyte|kilobytes
        TB=terabyte|terabytes
        °C=grado centígrado|grados centígrados
        °F=grado Fahrenheit|grados Fahrenheit
        °=grado|grados
        g=gramo|gramos
        m=metro|metros
        l=litro|litros
        h=hora|horas
    """)

    def cardinal_noun(self, n: int, feminine: bool = False) -> str:
        """«21» before a noun: veintiún / veintiuna, «200» before a feminine noun: doscientas."""
        tokens = num2words(n, lang="es").split(" ")
        scale = {"mil", "millón", "millones", "billón", "billones"}
        for i, t in enumerate(tokens):
            nxt = tokens[i + 1] if i + 1 < len(tokens) else None
            if t in ("uno", "veintiuno") and (nxt is None or nxt in scale):
                tokens[i] = {"uno": ("un", "una"), "veintiuno": ("veintiún", "veintiuna")}[t][feminine]
            elif feminine and t.endswith("ientos") and nxt not in ("millón", "millones", "billón", "billones"):
                tokens[i] = t[:-2] + "as"
        return " ".join(tokens)

    def ordinal_word(self, n: int, feminine: bool = False) -> str:
        w = num2words(n, lang="es", to="ordinal")
        return " ".join(t[:-1] + "a" if feminine and t.endswith("o") else t for t in w.split(" "))

    def roman_regnal(self, n: int, name: str) -> str:
        return self.ordinal_word(n, name in self.fem_names) if n <= 10 else self.number(str(n))

    def roman_century(self, n: int, ctx: str = "") -> str:
        return self.ordinal_word(n) if n <= 10 else self.number(str(n))

    def time_words(self, h: int, m: int, meridiem: str | None) -> str:
        hw = "una" if h == 1 else self.number(str(h))
        return f"{hw} y {self.number(str(m))}" if m else f"{hw} en punto"

    def dates(self, text: str) -> str:
        mo = "|".join(self.months)

        def numeric(m: re.Match) -> str:
            d, mth = int(m.group(1)), int(m.group(2))
            if not (1 <= d <= 31 and 1 <= mth <= 12):
                return m.group(0)
            return f"{'primero' if d == 1 else d} de {self.months[mth - 1]} de {m.group(3)}"

        text = re.sub(r"(?<![\d./-])(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})(?!\d)", numeric, text)
        return re.sub(rf"(?<![\d.,])\b1(?=\s+de\s+(?i:{mo})\b)", "primero", text)

    def ordinals(self, text: str) -> str:
        def one(m: re.Match) -> str:
            n, mark = int(m.group(1)), m.group(2)
            word = self.ordinal_word(n, mark == "ª")
            if mark == "er":  # apocope: primer, tercer
                word = re.sub(r"(primero|tercero)$", lambda x: x.group(1)[:-1], word)
            return word

        return re.sub(r"(?<![\w.,])(\d+)\.?(º|ª|er)(?![\w])", one, text)

    def agree(self, n: int, word: str) -> str | None:
        w = word.lower()
        if n == 1:
            if len(w) < 3 or w in STOP_ONE:
                return None
            return self.cardinal_noun(1, is_feminine(w))
        if not w.endswith("s") or w in STOP_PL or len(w) < 4:
            return None
        words = self.cardinal_noun(n, is_feminine(w))
        return words if words != num2words(n, lang="es") else None


register(Spanish())
