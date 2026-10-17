"""Languages without rules (pl, ar, hi, th, …): kept as they are, split on every script's terminators."""
import pytest
from test_cloud import Fake, job, make, ok

from folivox import lang
from folivox.lang.detect import detect
from folivox.lang.zh import Chinese
from folivox.qa.asr import ASR
from folivox.voicegen.cloud_apis import FishAudio


def test_get_returns_rule_less_language():
    pl = lang.get("pl")
    assert pl.code == "pl" and not lang.has_rules("pl") and lang.has_rules("ru")
    assert pl.normalize("W 2024 roku było 1250 osób, 17,5%.") == "W 2024 roku było 1250 osób, 17,5%."
    assert lang.get("pt-BR").code == "pt"
    assert "pl" not in [x.code for x in lang.available()]
    with pytest.raises(ValueError):
        lang.get("xx")


def test_normalize_cleans_quotes_and_dashes_only():
    assert lang.get("pl").normalize("«Cześć» -- powiedział  on.") == "Cześć — powiedział on."


@pytest.mark.parametrize("code,text,n", [
    ("ar", "هل أنت هنا؟ نعم. أين كنت؟", 3),
    ("hi", "तुम कहाँ हो। मैं यहाँ हूँ। ठीक है॥", 3),
    ("ur", "تم کہاں ہو۔ میں یہاں ہوں۔", 2),
    ("hy", "Ո՞վ ես։ Ես եմ։", 2),
    ("am", "እንዴት ነህ። ደህና ነኝ።", 2),
    ("el", "Πού είσαι; Εδώ. Καλά!", 3),
    ("th", "สวัสดีครับ ผมชื่อสมชาย ยินดีที่ได้รู้จัก", 3),
    ("pl", "Gdzie jesteś? Tu jestem. Dobrze!", 3),
])
def test_sentences_use_every_scripts_terminators(code, text, n):
    assert len(lang.get(code).sentences(text)) == n


def test_canonical_keeps_digits():
    assert lang.get("pl").canonical("Było 1250 osób!") == "było 1250 osób"


@pytest.mark.parametrize("code,text", [
    ("ar", "في عام ألفين وأربعة وعشرين كان هناك الكثير من الناس في المدينة القديمة"),
    ("hi", "यह एक बहुत पुरानी कहानी है जो हमारे गाँव में सुनाई जाती थी"),
    ("th", "นี่คือเรื่องเล่าเก่าแก่ที่เล่าต่อกันมาในหมู่บ้านของเรา"),
    ("el", "Αυτή είναι μια πολύ παλιά ιστορία που λέγεται στο χωριό μας"),
    ("he", "זהו סיפור ישן מאוד שמספרים בכפר שלנו"),
])
def test_detect_never_says_russian_for_other_scripts(code, text):
    assert detect(text) == code


def test_metadata_language_beats_latin_guess(tmp_path):
    from folivox.readers import read_book

    f = tmp_path / "b.fb2"
    f.write_text('<?xml version="1.0" encoding="utf-8"?><FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">'  # noqa: E501
                 '<description><title-info><genre>prose</genre><author><first-name>A</first-name><last-name>B</last-name>'  # noqa: E501
                 '</author><book-title>T</book-title><lang>pl</lang></title-info></description><body><section>'
                 '<p>The cat is on the mat and the dog is in the house with the man.</p>'
                 '</section></body></FictionBook>',
                 encoding="utf-8")
    assert read_book(f).lang == "pl"


def test_zh_ordinal_floor_is_er_not_liang():
    zh = Chinese()
    assert zh.normalize("住在第2层。") == "住在第二层。"
    assert "两个" in zh.normalize("有2个人。")


def test_whisper_language_only_when_known():
    assert ASR("pl").language == "pl" and ASR("nb").language == "no"
    assert ASR("ln-xx").language is None


def test_fish_languages_cover_the_nine_and_voice_languages():
    langs = set(FishAudio.languages)
    assert {"ru", "en", "zh", "pl", "ar", "th"} <= langs and set(FishAudio.voice_languages) <= langs


def test_fish_bytes_per_char_for_scripts():
    assert FishAudio.bytes_factor("hi") == 2.8 and FishAudio.bytes_factor("uk") == 1.85
    assert FishAudio.bytes_factor("pl") == 1.08


@pytest.mark.parametrize("code", ["pl", "ru", "ar", "th"])
def test_fish_request_never_normalizes_and_always_names_language(tmp_path, code):
    fake = Fake(ok(b"\0\0" * 2400))
    make(FishAudio, fake).generate([job(tmp_path, speaker="vid", lang=code, text="Tekst 1250.")])
    sent = fake.calls[0]["json"]
    assert sent["normalize"] is False and sent["language"] == code


# --- the language of a whole Latin-script book (lang/wordlists.py) -------------------------------------------

_SAMPLES = {
    "pt": "O governo anunciou ontem que as escolas vão reabrir na próxima segunda-feira, depois de várias semanas fechadas. Os alunos não têm muita vontade de voltar, mas os pais estão contentes com a decisão.",  # noqa: E501
    "pl": "Rząd ogłosił wczoraj, że szkoły zostaną otwarte w przyszły poniedziałek, po kilku tygodniach przerwy. Uczniowie nie są zadowoleni, ale rodzice się cieszą.",  # noqa: E501
    "nl": "De regering heeft gisteren aangekondigd dat de scholen volgende maandag weer opengaan, na enkele weken sluiting. De leerlingen zijn niet blij, maar de ouders wel.",  # noqa: E501
    "tr": "Hükümet dün okulların gelecek pazartesi yeniden açılacağını duyurdu. Öğrenciler pek memnun değil ama aileler sevindi ve bir şey söylemediler.",  # noqa: E501
    "cs": "Vláda včera oznámila, že školy se po několika týdnech znovu otevřou příští pondělí. Žáci nejsou nadšení, ale rodiče jsou spokojeni s jejím rozhodnutím.",  # noqa: E501
    "sv": "Regeringen meddelade igår att skolorna öppnar igen nästa måndag efter flera veckors stängning. Eleverna är inte glada, men föräldrarna är nöjda med beslutet.",  # noqa: E501
    "da": "Regeringen meddelte i går, at skolerne åbner igen på mandag efter flere ugers lukning. Eleverne er ikke glade, men forældrene er tilfredse med det.",  # noqa: E501
}


@pytest.mark.parametrize("code", sorted(_SAMPLES))
def test_latin_book_language_is_told_among_many(code):
    assert detect(_SAMPLES[code] * 5) == code


def test_arabic_script_tells_persian_and_urdu():
    assert detect("دولت دیروز اعلام کرد که مدرسه ها از هفته آینده دوباره باز می شوند و پدر و مادرها گفتند که چای را دوست دارند") == "fa"  # noqa: E501
    assert detect("حکومت نے کل اعلان کیا کہ اسکول اگلے ہفتے دوبارہ کھلیں گے اور بچے ٹھیک ہیں ڑ") == "ur"
    assert detect("أعلنت الحكومة أمس أن المدارس ستعيد فتح أبوابها يوم الاثنين المقبل") == "ar"


def test_qa_threshold_is_relaxed_without_rules():
    from folivox.qa import threshold_for

    text = "To jest dość długie zdanie, które ma więcej niż czterdzieści liter."
    assert threshold_for(text, 0.10, "pl") == pytest.approx(0.15)
    assert threshold_for(text, 0.10, "ru") == 0.10
