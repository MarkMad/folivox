"""Per-language reading rules beyond plain num2words: romans, dates, times, money, units, agreement."""

import pytest

from folivox import lang

CASES = [
    # English
    ("en", "Mr. Smith paid $5.50.", "Mister Smith paid five dollars fifty cents."),
    ("en", "Henry VIII and World War II, Chapter IV.", "Henry the eighth and World War two, Chapter four."),
    ("en", "In the XIX century.", "In the nineteenth century."),
    ("en", "On 21 July and July 4.", "On the twenty-first of July and July fourth."),
    ("en", "At 7:30 pm, at 7:05, at 7:00.", "At seven thirty p m, at seven oh five, at seven o'clock."),
    ("en", "3.5 kg, 1 km, 25°C.", "three point five kilograms, one kilometer, twenty-five degrees Celsius."),
    ("en", "$2.5 million.", "two point five million dollars."),
    ("en", "Malcolm X, in part I thought.", "Malcolm X, in part I thought."),
    # German
    ("de", "Am 3. Mai um 7:30 Uhr.", "Am dritten Mai um sieben Uhr dreißig."),
    ("de", "Der 1. Januar, am 3.5.2020.", "Der erste Januar, am dritten Mai zweitausendzwanzig."),
    ("de", "Ludwig XIV. regierte im XVII. Jahrhundert.", "Ludwig der Vierzehnte regierte im siebzehnten Jahrhundert."),
    ("de", "5,50 € und 2 kg, z.B. 25°C.",
     "fünf Euro fünfzig Cent und zwei Kilogramm, zum Beispiel fünfundzwanzig Grad Celsius."),
    ("de", "1 Mann, 1 Frau, 1 Uhr.", "ein Mann, eine Frau, ein Uhr."),
    # French
    ("fr", "Louis XIV, le XXe siècle, Chapitre I.", "Louis quatorze, le vingtième siècle, Chapitre premier."),
    ("fr", "Le 1er mai, la 2e fois, 03/05/2020.", "Le premier mai, la deuxième fois, trois mai deux mille vingt."),
    ("fr", "1 fille, 21 filles, 1 homme.", "une fille, vingt et une filles, un homme."),
    ("fr", "À 7h30, 5,50 €, 1,5 km.",
     "À sept heures trente, cinq euros cinquante centimes, un virgule cinq kilomètre."),
    # Spanish
    ("es", "21 mujeres, 200 casas, 21 hombres.", "veintiuna mujeres, doscientas casas, veintiún hombres."),
    ("es", "1 mujer, 1 hombre, el 21 de mayo.", "una mujer, un hombre, el veintiuno de mayo."),
    ("es", "El 1.º de mayo, la 3.ª vez, el 3.er piso.", "El primero de mayo, la tercera vez, el tercer piso."),
    ("es", "Siglo XIX, Felipe II, Isabel II.", "Siglo diecinueve, Felipe segundo, Isabel segunda."),
    ("es", "Sr. Pérez, 5,50 € a las 7:30.", "señor Pérez, cinco euros con cincuenta céntimos a las siete y treinta."),
    ("es", "2001 años, 221000 mujeres.", "dos mil un años, doscientas veintiuna mil mujeres."),
    # Italian
    ("it", "Il XIX secolo, Luigi XIV, Elisabetta II.",
     "Il diciannovesimo secolo, Luigi quattordicesimo, Elisabetta seconda."),
    ("it", "1º maggio, 1 maggio, la 3ª volta.", "primo maggio, primo maggio, la terza volta."),
    ("it", "1 gatto, 1 amica, 1 zaino.", "un gatto, un'amica, uno zaino."),
    ("it", "5,50 € alle 7:30, 25°C.",
     "cinque euro e cinquanta centesimi alle sette e trenta, venticinque gradi Celsius."),
    # Chinese
    ("zh", "我有2个朋友，200个人。", "我有两个朋友，两百个人。"),
    ("zh", "2024年3月5日，2000人。", "二零二四年三月五日，两千人。"),
    ("zh", "7:30起床，2:05到。", "七点三十分起床，两点零五分到。"),
    ("zh", "25°C，5km，¥5.5，增长12%，1,000本。", "二十五摄氏度，五公里，五点五元，增长百分之十二，一千本。"),
    # Japanese
    ("ja", "7:30に出発。$5と1,000円、25°C、50%。", "七時三十分に出発。五ドルと千円、二十五度、五十パーセント。"),
    # Korean
    ("ko", "3명이 2시간 걸었다. 20살.", "세 명이 두 시간 걸었다. 스무 살."),
    ("ko", "6월 10월 3월 5일, 1번째 3번째.", "유월 시월 삼월 오일, 첫 번째 세 번째."),
    ("ko", "7:30, ₩5,000, 25°C, 3개월.", "일곱 시 삼십분, 오천원, 섭씨 이십오도, 삼개월."),
]


@pytest.mark.parametrize(("code", "text", "expected"), CASES)
def test_reading_rules(code, text, expected):
    assert lang.get(code).normalize(text) == expected


@pytest.mark.parametrize("code", sorted({c for c, *_ in CASES}))
def test_canonical_matches_for_original_and_normalized(code):
    """QA compares the narrated text with Whisper's output: both go through the same reduction."""
    language = lang.get(code)
    for c, text, _ in CASES:
        if c == code:
            assert language.canonical(text) == language.canonical(language.normalize(text))


def test_no_empty_or_garbled_romans():
    assert lang.get("fr").normalize("M. Dupont") == "Monsieur Dupont"
    assert lang.get("en").normalize("Vitamin C and Plan B") == "Vitamin C and Plan B"


def test_imperial_units_and_french_ier():
    from folivox.lang import get
    assert get("en").normalize("He is 6 ft tall, 1 lb.") == "He is six feet tall, one pound."
    assert get("fr").normalize("François Ier et Élisabeth Ire.") == "François premier et Élisabeth première."
