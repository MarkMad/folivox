"""Russian text normalization for TTS: numbers, dates, abbreviations, symbols, punctuation.

The goal is "how a narrator would read it", not perfect grammar. Case/gender agreement is
handled for the frequent constructions (years, dates, ordinals with suffixes, units with
plural forms, prepositions governing the genitive/dative, feminine nouns after 1 and 2).
"""

from __future__ import annotations

import re
from collections.abc import Callable

from num2words import num2words

W = r"[А-Яа-яЁёA-Za-z]"
NUM_WORD_BOUNDARY = r"(?<![\w.,:])"


def _digits(n: float | str) -> str:
    """Digit by digit, for numbers num2words cannot read (too large)."""
    return " ".join(num2words(int(d), lang="ru") for d in str(n) if d.isdigit())


def cardinal(n: float | str, case: str = "n", gender: str = "m") -> str:
    try:
        return num2words(n, lang="ru", case=case, gender=gender)
    except (KeyError, IndexError, OverflowError):
        return _digits(n)


def ordinal(n: int, case: str = "n", gender: str = "m", plural: bool = False) -> str:
    return num2words(n, lang="ru", to="ordinal", case=case, gender=gender, plural=plural)


def plural_form(n: int, one: str, few: str, many: str) -> str:
    n = abs(n) % 100
    if 11 <= n <= 14:
        return many
    n %= 10
    return one if n == 1 else few if 2 <= n <= 4 else many


# ---------------------------------------------------------------- dictionaries

MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября",
              "октября", "ноября", "декабря"]
MONTHS_RE = "|".join(MONTHS_GEN)

# Prepositions that put a following number into a given case.
PREP_CASE = {
    **dict.fromkeys(["до", "от", "около", "после", "из", "без", "для", "кроме", "свыше", "более", "менее",
                     "больше", "меньше", "у", "против", "среди", "вместо", "посреди"], "g"),
    **dict.fromkeys(["к", "ко", "согласно", "благодаря"], "d"),
    **dict.fromkeys(["между", "над", "под", "перед"], "i"),
    **dict.fromkeys(["о", "об", "при"], "p"),
}

# unit abbreviation → (gender, one, few, many, genitive singular for fractions)
UNITS: dict[str, tuple[str, str, str, str]] = {
    "кг": ("m", "килограмм", "килограмма", "килограммов"),
    "км": ("m", "километр", "километра", "километров"),
    "км/ч": ("m", "километр в час", "километра в час", "километров в час"),
    "м": ("m", "метр", "метра", "метров"),
    "см": ("m", "сантиметр", "сантиметра", "сантиметров"),
    "мм": ("m", "миллиметр", "миллиметра", "миллиметров"),
    "л": ("m", "литр", "литра", "литров"),
    "мл": ("m", "миллилитр", "миллилитра", "миллилитров"),
    "т": ("f", "тонна", "тонны", "тонн"),
    "ч": ("m", "час", "часа", "часов"),
    "мин": ("f", "минута", "минуты", "минут"),
    "сек": ("f", "секунда", "секунды", "секунд"),
    "руб": ("m", "рубль", "рубля", "рублей"),
    "р": ("m", "рубль", "рубля", "рублей"),
    "коп": ("f", "копейка", "копейки", "копеек"),
    "тыс": ("f", "тысяча", "тысячи", "тысяч"),
    "млн": ("m", "миллион", "миллиона", "миллионов"),
    "млрд": ("m", "миллиард", "миллиарда", "миллиардов"),
    "трлн": ("m", "триллион", "триллиона", "триллионов"),
    "%": ("m", "процент", "процента", "процентов"),
    "$": ("m", "доллар", "доллара", "долларов"),
    "€": ("m", "евро", "евро", "евро"),
    "₽": ("m", "рубль", "рубля", "рублей"),
    "°C": ("m", "градус Цельсия", "градуса Цельсия", "градусов Цельсия"),
    "°": ("m", "градус", "градуса", "градусов"),
}
UNIT_GEN_SG = {k: v[2] for k, v in UNITS.items()}  # "3,5 кг" → "килограмма"

ABBREVIATIONS: list[tuple[str, str]] = [
    (r"и\s?т\.\s?д\.", "и так далее"),
    (r"и\s?т\.\s?п\.", "и тому подобное"),
    (r"т\.\s?е\.", "то есть"),
    (r"т\.\s?к\.", "так как"),
    (r"т\.\s?н\.", "так называемый"),
    (r"в\s?т\.\s?ч\.", "в том числе"),
    (r"и\s?др\.", "и другие"),
    (r"и\s?пр\.", "и прочее"),
    (r"до\s?н\.\s?э\.", "до нашей эры"),
    (r"н\.\s?э\.", "нашей эры"),
    (r"см\.(?=\s)", "смотри"),
    (r"напр\.", "например"),
    (r"г-н", "господин"),
    (r"г-жа", "госпожа"),
    (r"ул\.", "улица"),
    (r"пр-т", "проспект"),
    (r"пер\.(?=\s+[А-ЯЁ])", "переулок"),
    (r"д\.(?=\s*\d)", "дом"),
    (r"кв\.(?=\s*\d)", "квартира"),
    (r"стр\.(?=\s*\d)", "страница"),
    (r"рис\.(?=\s*\d)", "рисунок"),
    (r"тел\.", "телефон"),
    (r"проф\.", "профессор"),
    (r"акад\.", "академик"),
    (r"им\.(?=\s+[А-ЯЁ])", "имени"),
    (r"св\.(?=\s+[А-ЯЁ])", "святой"),
]
_ABBR = [(re.compile(rf"(?<![\w-]){p}(?!\w)"), r) for p, r in ABBREVIATIONS]

ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
ROMAN_RE = r"(?=[MDCLXVI])(?:M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3}))"


def roman_to_int(s: str) -> int:
    total, prev = 0, 0
    for ch in reversed(s.upper()):
        v = ROMAN[ch]
        total = total - v if v < prev else total + v
        prev = max(prev, v)
    return total


# Ordinal suffix after a hyphen → (case, gender, plural). Ambiguous ones resolved by context.
SUFFIX_FORMS = {
    "й": ("n", "m", False), "ый": ("n", "m", False), "ий": ("n", "m", False), "ой": None,
    "я": ("n", "f", False), "ая": ("n", "f", False),
    "е": ("n", "n", False), "ое": ("n", "n", False), "ые": ("n", "m", True),
    "го": ("g", "m", False), "ого": ("g", "m", False),
    "му": ("d", "m", False), "ому": ("d", "m", False),
    "м": None, "ым": None, "ом": ("p", "m", False),
    "ю": ("a", "f", False), "ую": ("a", "f", False),
    "х": ("p", "m", True), "ых": ("p", "m", True),
    "ми": ("i", "m", True), "ыми": ("i", "m", True),
}

# Chapter-like nouns read with an ordinal: «Глава 3» → «Глава третья».
ORDINAL_NOUNS = {"глава": "f", "часть": "f", "книга": "f", "серия": "f", "том": "m", "раздел": "m",
                 "акт": "m", "эпизод": "m", "сезон": "m", "день": "m", "урок": "m", "выпуск": "m"}
CENTURY_FORMS = {"век": "n", "века": "g", "веке": "p", "веку": "d", "веком": "i", "веков": "g", "веках": "p",
                 "столетие": "n", "столетия": "g", "столетии": "p"}
YEAR_FORMS = {"год": "n", "года": "g", "году": "p", "годом": "i", "годах": "p", "годов": "g", "годы": "n",
              "годам": "d", "годами": "i"}


def _prev_word(text: str, start: int) -> str:
    m = re.search(r"([А-Яа-яЁё]+)\W*$", text[max(0, start - 30):start])
    return m.group(1).lower() if m else ""


def _period(t: str, end: int) -> str:
    """A consumed abbreviation dot that also ended the sentence must be restored."""
    rest = t[end:]
    return "." if not rest.strip() or re.match(r"\s+[А-ЯЁA-Z—–-]", rest) else ""


def _int(s: str) -> int:
    return int(re.sub(r"\D", "", s))


# ---------------------------------------------------------------- rules


def _sub(pattern: str, fn: Callable[[re.Match, str], str], text: str, flags: int = 0) -> str:
    rx = re.compile(pattern, flags)
    out, pos = [], 0
    for m in rx.finditer(text):
        out.append(text[pos:m.start()])
        out.append(fn(m, text))
        pos = m.end()
    out.append(text[pos:])
    return "".join(out)


def _dates(text: str) -> str:
    def numeric(m, t):
        d, mo, y = int(m.group(1)), int(m.group(2)), m.group(3)
        if not (1 <= d <= 31 and 1 <= mo <= 12):
            return m.group(0)
        case = "g" if PREP_CASE.get(_prev_word(t, m.start())) == "g" else "n"
        out = f"{ordinal(d, case, 'n')} {MONTHS_GEN[mo - 1]}"
        if y:
            yi = int(y) if len(y) == 4 else 2000 + int(y) if int(y) < 50 else 1900 + int(y)
            out += f" {ordinal(yi, 'g')} года"
        return out

    text = _sub(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})\b(?:\s*г\.)?", numeric, text)

    def day_month(m, t):
        prep = _prev_word(t, m.start())
        case = {"g": "g", "d": "d"}.get(PREP_CASE.get(prep, ""), "n")
        if prep in ("по", "на") or prep == "с":
            case = {"по": "a", "на": "a", "с": "g"}[prep]
        return f"{ordinal(int(m.group(1)), case, 'n')} {m.group(2)}"

    return _sub(rf"\b(\d{{1,2}})\s+({MONTHS_RE})\b", day_month, text, re.IGNORECASE)


def _years(text: str) -> str:
    def with_noun(m, t):
        n, noun = _int(m.group(1)), m.group(2).lower()
        if n < 1000 and not (noun in ("году", "года") and _prev_word(t, m.start()) in ("в", "во", "с", "до")):
            return m.group(0)  # «21 год», «22 года» are durations / ages
        if noun in ("г.", "г"):
            prev = _prev_word(t, m.start())
            dot = _period(t, m.end()) if noun.endswith(".") else ""
            if prev in ("в", "во"):
                return f"{ordinal(n, 'p')} году{dot}"
            if prev in MONTHS_GEN or PREP_CASE.get(prev) == "g" or prev in ("с", "со"):
                return f"{ordinal(n, 'g')} года{dot}"
            return (f"{ordinal(n, 'g')} года" if prev else f"{ordinal(n)} год") + dot
        if noun in ("гг.", "гг"):
            prep = _prev_word(t, m.start()) in ("в", "во")
            return f"{ordinal(n, 'p' if prep else 'n', plural=True)} {'годах' if prep else 'годы'}" + \
                _period(t, m.end())
        case = YEAR_FORMS[noun]
        if noun == "году" and _prev_word(t, m.start()) in ("к", "по"):
            case = "d"
        plural = noun in ("годах", "годов", "годы", "годам", "годами")
        return f"{ordinal(n, case, plural=plural)} {m.group(2)}"

    nouns = "|".join(sorted(YEAR_FORMS, key=len, reverse=True))
    text = _sub(rf"\b(\d{{1,4}})\s*({nouns}|гг\.?|г\.)(?!\w)", with_noun, text, re.IGNORECASE)

    # bare year after «в»: «в 1999 он…» → «в тысяча девятьсот девяносто девятом»
    def bare(m, t):
        return f"{m.group(1)} {ordinal(int(m.group(2)), 'p')}"

    return _sub(r"\b([Вв]о?)\s+(1[0-9]{3}|20[0-9]{2})\b(?![\s]*[-–—%]|\s*(?:[а-яё]+[аиыоу]в?\b))", bare, text)


def _centuries(text: str) -> str:
    def abbr(n: int, plural: bool, prev: str) -> str:
        if prev in ("в", "во"):
            return f"{ordinal(n, 'p', plural=plural)} {'веках' if plural else 'веке'}"
        if PREP_CASE.get(prev) == "g" or prev in ("с", "со"):
            return f"{ordinal(n, 'g', plural=plural)} {'веков' if plural else 'века'}"
        return f"{ordinal(n, plural=plural)} {'века' if plural else 'век'}"

    def fn(m, t):
        n = int(m.group(1)) if m.group(1).isdigit() else roman_to_int(m.group(1))
        noun = m.group(2)
        if noun in ("в.", "вв."):
            return abbr(n, noun == "вв.", _prev_word(t, m.start())) + _period(t, m.end())
        g = "n" if noun.lower().startswith("столет") else "m"
        return f"{ordinal(n, CENTURY_FORMS[noun.lower()], g, plural=noun.lower() in ('веков', 'веках'))} {noun}"

    nouns = "|".join(sorted(CENTURY_FORMS, key=len, reverse=True))
    return _sub(rf"\b({ROMAN_RE}|\d{{1,2}})\s*({nouns}|вв\.|в\.)(?!\w)", fn, text)


def _ordinal_suffixes(text: str) -> str:
    def fn(m, t):
        n, suf = _int(m.group(1)), m.group(2).lower()
        form = SUFFIX_FORMS.get(suf)
        prev = _prev_word(t, m.start())
        nxt = t[m.end():m.end() + 20].lstrip().lower()
        if form is None:
            if suf in ("м", "ым"):
                form = ("p", "m", False) if prev in ("в", "во", "на", "о", "об", "при") else ("i", "m", False)
                if re.match(r"[а-яё]+(ах|ях)\b", nxt):
                    form = ("p", "m", True)
            else:  # "ой": genitive/dative/instrumental/prepositional feminine, or masc nominative
                form = ("g", "f", False)
        case, g, pl = form
        if suf in ("е",) and re.match(r"[а-яё]+(ые|ие|ы|и)\b", nxt):
            pl = True
        if suf in ("х", "ых") and PREP_CASE.get(prev) == "g":
            case = "g"
        return ordinal(n, case, g, pl)

    return _sub(r"\b(\d+)\s?-\s?(ыми|ый|ий|ой|ая|ое|ые|ого|ому|ым|ом|ую|ых|ми|го|му|й|я|е|м|ю|х)\b", fn, text)


def _ordinal_nouns(text: str) -> str:
    nouns = "|".join(ORDINAL_NOUNS)

    def fn(m, t):
        word, num = m.group(1), m.group(2)
        n = roman_to_int(num) if not num.isdigit() else int(num)
        if n == 0:
            return m.group(0)
        return f"{word} {ordinal(n, 'n', ORDINAL_NOUNS[word.lower()])}"

    return _sub(rf"\b({nouns})\s+({ROMAN_RE}|\d{{1,3}})\b(?![.,]\d)", fn, text, re.IGNORECASE)


def _regnal(text: str) -> str:
    # «Пётр I», «Екатерина II», «Людовик XIV»
    def fn(m, t):
        name, num = m.group(1), m.group(2)
        if not num:
            return m.group(0)
        g = "f" if name[-1] in "аяь" and name not in ("Илья", "Никита", "Фома", "Кузьма", "Лука") else "m"
        return f"{name} {ordinal(roman_to_int(num), 'n', g).capitalize()}"

    return _sub(rf"\b([А-ЯЁ][а-яё]{{2,}})\s+({ROMAN_RE})\b(?!\.\w)", fn, text)


def _time(text: str) -> str:
    def fn(m, t):
        h, mi = int(m.group(1)), int(m.group(2))
        if h > 24 or mi > 59:
            return m.group(0)
        hw = cardinal(h)
        if mi == 0:
            return f"{hw} ноль-ноль"
        mw = cardinal(mi, gender="f")
        return f"{hw} {'ноль ' if mi < 10 else ''}{mw}"

    return _sub(r"\b(\d{1,2}):(\d{2})\b(?!:)", fn, text)


def _number_sign(text: str) -> str:
    return re.sub(r"№\s*(\d+)", lambda m: f"номер {cardinal(int(m.group(1)))}", text).replace("№", "номер")


def _decimal_words(s: str, case: str = "n") -> str:
    s = s.replace(",", ".")
    try:
        return num2words(float(s), lang="ru", case=case) if case != "n" else num2words(float(s), lang="ru")
    except (TypeError, ValueError, NotImplementedError):
        try:
            return num2words(float(s), lang="ru")
        except (ValueError, KeyError, IndexError, OverflowError):  # too large for num2words
            return _digits(s)


def _units(text: str) -> str:
    keys = sorted(UNITS, key=len, reverse=True)
    unit_re = "|".join(re.escape(k) for k in keys)

    def fn(m, t):
        num, unit = m.group(2), m.group(3) or m.group(1)
        dot = _period(t, m.end()) if m.group(0).endswith(".") else ""
        unit = unit.rstrip(".")
        if unit not in UNITS:
            return m.group(0)
        g, one, few, many = UNITS[unit]
        prev = _prev_word(t, m.start())
        case = PREP_CASE.get(prev, "n")
        if re.search(r"[.,]\d", num):
            return f"{_decimal_words(num)} {UNIT_GEN_SG[unit]}{dot}"
        n = _int(num)
        words = cardinal(n, case, g)
        if case == "n":
            noun = plural_form(n, one, few, many)
        else:
            noun = many if n % 10 != 1 or n % 100 == 11 else few  # genitive-ish approximation
        return f"{words} {noun}{dot}"

    # currency sign before the number: $5, € 10
    text = _sub(r"([$€₽])\s?(\d+(?:[\u00a0\u202f ]\d{3})*(?:[.,]\d+)?)()", fn, text)
    text = re.sub(r"(?:(?<=\s)|^)[-−](?=\d+\s?°)", "минус ", text)
    return _sub(rf"(?<![\w.])()(\d+(?:[\u00a0\u202f ]\d{{3}})*(?:[.,]\d+)?)\s?({unit_re})(?:\.)?(?![\wА-Яа-яЁё])",
                fn, text)


_FEM_HINT_2 = re.compile(r"^[а-яё]+[ыи]\b")


def _gender_for(n: int, following: str) -> str:
    w = following.lower()
    if n % 10 == 1 and n % 100 != 11:
        if re.match(r"^[а-яё]+[ая]\b", w) and not re.match(r"^[а-яё]+(ого|его)\b", w):
            return "f"
        if re.match(r"^[а-яё]+[ое]\b", w) and not re.match(r"^[а-яё]+(ой|ей)\b", w):
            return "n"
    if n % 10 == 2 and n % 100 != 12 and _FEM_HINT_2.match(w):
        return "f"
    return "m"


def _cardinals(text: str) -> str:
    text = re.sub(r"(?:(?<=\s)|^)[-−–](?=\d)", "минус ", text)
    # decimals
    text = _sub(r"(?<![\w.,])(\d+)[.,](\d{1,3})(?![\d.,]\d)", lambda m, t: _decimal_words(
        f"{m.group(1)}.{m.group(2)}", PREP_CASE.get(_prev_word(t, m.start()), "n")), text)

    # ranges 5–7, 10-15 → "от пяти до семи" is too clever; read as "пять — семь"
    def rng(m, t):
        return f"{m.group(1)} — {m.group(2)}"

    text = _sub(r"\b(\d+)\s?[–—-]\s?(\d+)\b", rng, text)

    def fn(m, t):
        n = _int(m.group(1))
        prev = _prev_word(t, m.start())
        following = t[m.end():m.end() + 25].lstrip()
        case = PREP_CASE.get(prev, "n")
        # «с 5 до 7»: the «с» here is genitive
        if prev in ("с", "со") and re.match(r"^до\s", following):
            case = "g"
        gender = _gender_for(n, following)
        if case == "n" and n % 10 == 1 and n % 100 != 11 and re.match(r"^[а-яё]+[^о][ую]\b", following.lower()) \
                and not re.match(r"^[а-яё]+(ому|ему)\b", following.lower()):
            case, gender = "a", "f"  # «съел 21 грушу» → «двадцать одну»
        return cardinal(n, case, gender)

    return _sub(r"(?<![\w])(\d{1,3}(?:[\u00a0\u202f ]\d{3})+|\d+)(?!\w)", fn, text)


def _symbols(text: str) -> str:
    rep = {"&": " и ", "§": " параграф ", "=": " равно ", "+": " плюс ", "×": " на ", "½": " половина ",
           "¼": " четверть ", "@": " собака "}
    for k, v in rep.items():
        text = text.replace(k, v)
    return text


# ---------------------------------------------------------------- punctuation for TTS

QUOTES = "«»„“”‟\"‘’‚‹›"


def punctuation(text: str) -> str:
    text = text.replace("...", "…").replace("--", "—")
    text = re.sub(r"\s[–-]\s", " — ", text)
    text = re.sub(r"^[–-]\s", "— ", text)
    text = re.sub(r"\[\d+\]|\{\d+\}", "", text)  # footnote refs left in text
    text = re.sub(f"[{QUOTES}]", "", text)
    text = re.sub(r"\*{1,3}", "", text)
    text = re.sub(r"[_~^|<>]", " ", text)
    text = re.sub(r"\(\s*\)", "", text)
    text = re.sub(r"([!?…])\1+", r"\1", text)
    text = re.sub(r"!\?|\?!", "?", text)
    return text


def dialogue(text: str) -> str:
    """Strip dialogue dashes the narrator does not pronounce.

    «— Ты куда? — спросила соседка.» → «Ты куда? — спросила соседка.» The dash before an
    attribution is kept: CosyVoice renders it as a short pause, which is what a narrator does.
    """
    return re.sub(r"^\s*—\s*", "", text)


def collapse(text: str) -> str:
    text = re.sub(r"[ \t\u00a0\u202f]+", " ", text)
    text = re.sub(r"\s+([,.!?;:…])", r"\1", text)
    return text.strip()


def capitalize_sentences(text: str) -> str:
    return re.sub(r"(^|[.!?…]\s+)([а-яё])", lambda m: m.group(1) + m.group(2).upper(), text)


_CLAUSE_WORD = r"(?:пункт\w*|подпункт\w*|раздел\w*|стать\w+|глав\w+|приложени\w+|параграф\w*|част[ьи]|абзац\w*)"
_NUM = r"\d+(?:\.\d+)+"


def _dotted(num: str) -> str:
    """«2.3» as a clause number: «два точка три», not «две целых три десятых»."""
    return " точка ".join(cardinal(int(part)) for part in num.split("."))


def _clause_numbers(text: str) -> str:
    """Numbers of contract clauses (2.3, 1.2.3) are read digit group by digit group.

    Three levels or more are never decimals. Two levels are clause numbers at the start of a paragraph
    followed by a capitalised sentence («2.3. Арендатор обязан…») or right after a word like «пункт»
    («пунктами 2.3 и 2.4»); elsewhere «2.5» stays a decimal."""
    text = re.sub(r"(?<![\w.])пп\.\s*(?=\d)", "подпункты ", text)  # «пп. 2.1» / «п. 2.3» before a number only
    text = re.sub(r"(?<![\w.])п\.\s*(?=\d)", "пункт ", text)
    text = re.sub(r"\b\d+(?:\.\d+){2,}\b", lambda m: _dotted(m.group(0)), text)
    text = re.sub(rf"^(\s*)({_NUM})\.?(?=\s+[«\"(А-ЯЁA-Z])", lambda m: m.group(1) + _dotted(m.group(2)) + ".", text)

    def after_word(m: re.Match) -> str:
        return m.group(1) + re.sub(_NUM, lambda n: _dotted(n.group(0)), m.group(2))

    return re.sub(rf"(?i)(\b{_CLAUSE_WORD}\s*)({_NUM}(?:\s*(?:,|и|или|до|по|—|-)\s*{_NUM})*)", after_word, text)


def normalize(text: str) -> str:
    """Full pipeline for one paragraph (or heading)."""
    text = punctuation(text)
    for rx, rep in _ABBR:
        text = _sub(rx.pattern, lambda m, t, rep=rep: rep + (_period(t, m.end()) if m.group(0).endswith(".")
                                                           else ""), text)
    text = _number_sign(text)
    text = _dates(text)
    text = _clause_numbers(text)
    text = _time(text)
    text = _centuries(text)
    text = _years(text)
    text = _ordinal_suffixes(text)
    text = _ordinal_nouns(text)
    text = _regnal(text)
    text = _units(text)
    text = _cardinals(text)
    text = _symbols(text)
    return capitalize_sentences(collapse(text))


def has_speech(text: str) -> bool:
    """False for separators like «* * *» that should become a pause."""
    return bool(re.search(r"[А-Яа-яЁёA-Za-z0-9]", text))
