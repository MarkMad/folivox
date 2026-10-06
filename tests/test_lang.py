import pytest

from folivox import lang
from folivox.book import Block, BlockKind, Chapter
from folivox.lang.detect import detect
from folivox.lang.zh import zh_int
from folivox.qa import canonical, cer, score
from folivox.readers.headings import heading_level
from folivox.text.chunk import ChunkOptions, plan_chapter, sentences

CASES = {
    # code: (text, expected sentences after normalisation, a heading line)
    "en": ("In 1984 Mr. Smith paid $5. He left on the 2nd day.",
           ["In nineteen eighty-four Mr. Smith paid five dollars.", "He left on the second day."], "Chapter 12"),
    "de": ("Im Jahr 1984 kamen 10.000 Leute, z.B. Hans. Er ging.",
           ["Im Jahr neunzehnhundertvierundachtzig kamen zehntausend Leute, z.B. Hans.", "Er ging."],
           "Kapitel 3"),
    "fr": ("M. Dupont avait 3 chats. Il partit.", ["M. Dupont avait trois chats.", "Il partit."], "Chapitre IV"),
    "es": ("El Sr. Pérez tenía 3 gatos. Se fue.", ["El Sr. Pérez tenía tres gatos.", "Se fue."], "Capítulo 2"),
    "it": ("Il sig. Rossi aveva 3 gatti. Partì.", ["Il sig. Rossi aveva tre gatti.", "Partì."], "Capitolo 7"),
    "zh": ("他有305本书。他走了！", ["他有三百零五本书。", "他走了！"], "第三章 风"),
    "ja": ("本が3冊ある。彼は去った。", ["本が三冊ある。", "彼は去った。"], "第1章"),
    "ko": ("책이 3권 있다. 그는 떠났다.", ["책이 삼권 있다.", "그는 떠났다."], "제 3 장"),
    "ru": ("В 1984 году было 3 кг. Он ушёл.",
           ["В тысяча девятьсот восемьдесят четвёртом году было три килограмма.", "Он ушёл."], "Глава 5"),
}


def test_all_supported_languages_have_cases():
    assert set(CASES) == set(lang.SUPPORTED)


@pytest.mark.parametrize("code", sorted(CASES))
def test_normalize_and_split(code):
    text, expected, _ = CASES[code]
    language = lang.get(code)
    assert language.sentences(language.normalize(text)) == expected


@pytest.mark.parametrize("code", sorted(CASES))
def test_chapter_heading(code):
    assert heading_level(CASES[code][2]) == 2


@pytest.mark.parametrize("code", sorted(CASES))
def test_qa_identity_and_numbers(code):
    text, expected, _ = CASES[code]
    assert cer(text, " ".join(expected), code) == 0
    assert canonical(text, code) == canonical(" ".join(expected), code)


@pytest.mark.parametrize("code", sorted(CASES))
def test_plan_chapter(code):
    text, expected, _ = CASES[code]
    ch = Chapter("t", [Block(BlockKind.PARAGRAPH, text)])
    chunks = plan_chapter(ch, ChunkOptions(lang=code, stress="none", max_chars=20))
    assert "".join(c.text for c in chunks).replace(" ", "") == "".join(expected).replace(" ", "")


def test_language_codes():
    assert lang.get("ru-RU").code == "ru"
    assert lang.get("eng").code == "en"
    assert lang.get("zh_Hans").code == "zh"
    with pytest.raises(ValueError):
        lang.get("xx")


def test_zh_numbers():
    assert zh_int(10) == "十"
    assert zh_int(15) == "十五"
    assert zh_int(105) == "一百零五"
    assert zh_int(1010) == "一千零一十"
    assert zh_int(20000) == "两万" or zh_int(20000) == "二万"
    assert zh_int(100005) == "十万零五"


def test_detect():
    assert detect("Он вошёл в комнату и сел у окна.") == "ru"
    assert detect("He walked into the room and sat down by the window, and the sun was in his eyes.") == "en"
    assert detect("Er ging in das Zimmer und setzte sich ans Fenster, und die Sonne war nicht da.") == "de"
    assert detect("Il entra dans la chambre et il se mit à la fenêtre, et le soleil est dans les yeux.") == "fr"
    assert detect("Entró en la habitación y se sentó junto a la ventana, pero el sol no estaba.") == "es"
    assert detect("Entrò nella stanza e si sedette alla finestra, ma il sole non c'era per lui.") == "it"
    assert detect("他走进房间，坐在窗边。") == "zh"
    assert detect("彼は部屋に入って、窓のそばに座った。") == "ja"
    assert detect("그는 방에 들어가 창가에 앉았다.") == "ko"


def test_cjk_split_keeps_no_spaces():
    assert sentences("他来了。他走了。", "zh") == ["他来了。", "他走了。"]


def test_speaking_rate_per_language():
    # 20 CJK characters in 4 s is normal Chinese narration, far too slow for Russian letters
    ref = "他走进房间坐在窗边看着外面的雨一直下个不停"
    assert score(ref, ref, 4.0, "zh") == 0
