"""The studio's message catalogs: same keys and placeholders in every language, and every key the page uses exists."""

import json
import re
from pathlib import Path

import pytest

from folivox import lang as languages

STATIC = Path(__file__).parent.parent / "src" / "folivox" / "ui" / "static"
CATALOGS = STATIC / "i18n"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")

# Keys a language may leave untranslated (it then shows the English text): {code: {key, ...}}. Keep this short.
ALLOW_MISSING: dict[str, set[str]] = {}
# Keys built at run time ("cover.state." + kind), so a literal scan cannot see them.
DYNAMIC_PREFIXES = ("cover.state.", "g.", "used.", "mode.", "kind.", "stage.", "gp.idea.", "engine.", "fish.points.")
NATIVE = {"ru": "Русский", "es": "Español", "de": "Deutsch", "fr": "Français", "it": "Italiano",
          "zh": "中文", "ja": "日本語", "ko": "한국어", "en": "English"}


def load(code):
    return json.loads((CATALOGS / f"{code}.json").read_text(encoding="utf-8"))


CODES = sorted(p.stem for p in CATALOGS.glob("*.json"))
EN = load("en")


def params(text):
    return sorted(re.findall(r"\{(\w+)\}", text))


def tags(text):
    return [re.sub(r"\s+", " ", t) for t in re.findall(r"<[^>]+>", text)]


def used_keys():
    keys = set(re.findall(r'data-i18n(?:-html)?="([^"]+)"', INDEX))
    for spec in re.findall(r'data-i18n-attr="([^"]+)"', INDEX):
        keys |= {part.split(":", 1)[1] for part in spec.split(";")}
    keys |= set(re.findall(r'\b(?:t|tr)\("([^"]+)"[,)]', INDEX))
    keys |= set(re.findall(r'"((?:stage|gp\.idea)\.[\w.]+)"', INDEX))
    return keys


def test_every_book_language_has_a_catalog():
    assert set(CODES) == set(languages.SUPPORTED)


@pytest.mark.parametrize("code", CODES)
def test_catalog_is_valid_json_of_strings(code):
    data = load(code)
    assert isinstance(data, dict) and data
    assert all(isinstance(k, str) and isinstance(v, str) and v.strip() for k, v in data.items()), code


@pytest.mark.parametrize("code", [c for c in CODES if c != "en"])
def test_same_keys_as_english(code):
    data, allowed = load(code), ALLOW_MISSING.get(code, set())
    missing = sorted(set(EN) - set(data) - allowed)
    extra = sorted(set(data) - set(EN))
    assert not missing, f"{code}: missing keys {missing}"
    assert not extra, f"{code}: keys not in English {extra}"


@pytest.mark.parametrize("code", [c for c in CODES if c != "en"])
def test_placeholders_and_markup_match_english(code):
    bad = [k for k, v in load(code).items() if k in EN and (params(v) != params(EN[k]) or tags(v) != tags(EN[k]))]
    assert not bad, f"{code}: placeholders or HTML tags differ from English in {bad}"


def test_every_key_used_by_the_page_exists_in_english():
    missing = sorted(k for k in used_keys() if k not in EN)
    assert not missing, f"keys used in index.html but absent from en.json: {missing}"


def test_dynamic_key_families_exist():
    for key in ("cover.state.custom", "cover.state.book", "cover.state.none", "cover.state.empty", "g.f", "g.m",
                "used.tts", "used.voicegen", "used.asr", "used.llm", "stage.prepare", "stage.encode"):
        assert key in EN, key
    for mode in ("preset", "design", "localize", "clone"):
        assert f"mode.{mode}.h" in EN and f"mode.{mode}.s" in EN
    for name in ("cosyvoice3", "fish-s2", "fish-drama3", "gemini", "openai", "elevenlabs", "cartesia"):
        assert f"engine.{name}.blurb" in EN
    for kind in ("tts", "asr", "llm", "voicegen"):
        assert f"kind.{kind}.h" in EN and f"kind.{kind}.s" in EN


def test_no_orphan_english_keys():
    # also keys named in tables and ternaries: any quoted literal in the page that is a catalog key
    used = used_keys() | {k for k in re.findall(r'["\']([\w.]+)["\']', INDEX) if k in EN}
    orphans = sorted(k for k in EN if k not in used and not k.startswith(DYNAMIC_PREFIXES))
    assert not orphans, f"keys in en.json that the page never uses: {orphans}"


def test_language_switcher_lists_exactly_the_supported_languages():
    block = re.search(r"const UI_LANGS = \[(.*?)\];", INDEX, re.S).group(1)
    listed = dict(re.findall(r'\["(\w+)", "([^"]+)"\]', block))
    assert listed == NATIVE
    assert set(listed) == set(CODES) == set(languages.SUPPORTED)


def test_html_lang_and_switcher_markup():
    assert '<html lang="en">' in INDEX and 'id="ui-lang"' in INDEX


# ---- the route that serves the catalogs ---------------------------------------------------------------------------
@pytest.fixture
def client(tmp_path, monkeypatch):
    pytest.importorskip("starlette")
    pytest.importorskip("httpx")
    from starlette.testclient import TestClient

    from folivox import config
    from folivox.ui.app import create_app

    monkeypatch.setenv("FOLIVOX_CONFIG", str(tmp_path / "config.toml"))
    config.load.cache_clear()
    app = create_app(token="t0ken", port=8765, data_dir=tmp_path / "ui")
    yield TestClient(app, base_url="http://127.0.0.1:8765")
    config.load.cache_clear()


@pytest.mark.parametrize("code", CODES)
def test_catalog_route_serves_the_file(client, code):
    r = client.get(f"/i18n/{code}.json")  # static text, so no token is needed, but the Host guard still applies
    assert r.status_code == 200 and r.json() == load(code)


def test_catalog_route_rejects_unknown_codes_and_foreign_hosts(client):
    assert client.get("/i18n/xx.json").status_code == 404
    assert client.get("/i18n/..%2Findex.json").status_code in (404, 400)
    assert client.get("/i18n/en.json", headers={"host": "evil.example:8765"}).status_code == 403
