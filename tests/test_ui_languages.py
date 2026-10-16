"""Studio: the languages of a book, per speaker, and the gaps of their voices."""

import pytest

pytest.importorskip("starlette")
pytest.importorskip("httpx")

from starlette.testclient import TestClient  # noqa: E402

from folivox import config  # noqa: E402
from folivox.ui.app import create_app  # noqa: E402

TOKEN = "t0ken"
RU = "Это длинный русский абзац про урок, в нём нет ничего чужого и он просто читается спокойно. " * 3
MIX = "Слово пишется так: Good morning, everyone! А читается медленно и очень внятно, как просил учитель."
BOOK = ("Глава 1\n\n" + RU + "\n\n" + MIX + "\n\n" + (MIX + "\n\n") * 6).encode()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FOLIVOX_CONFIG", str(tmp_path / "config.toml"))
    config.load.cache_clear()
    app = create_app(token=TOKEN, port=8765, data_dir=tmp_path / "ui", render=lambda b, o, e: o.output)
    c = TestClient(app, base_url="http://127.0.0.1:8765", headers={"X-Folivox-Token": TOKEN})
    yield c
    config.load.cache_clear()


def upload(client, body=BOOK):
    return client.post("/api/books", files={"file": ("b.txt", body, "text/plain")}).json()["book_id"]


def test_language_shares_and_the_narrator_voice(client):
    bid = upload(client)
    r = client.get(f"/api/books/{bid}/languages").json()
    assert r["lang"] == "ru" and list(r["shares"])[:2] == ["ru", "en"] and 0.02 < r["shares"]["en"] < 0.2
    narrator = r["speakers"]["0"]
    assert narrator["letters"]["en"] > 40
    assert narrator["voice_lang"] == "ru" and narrator["gaps"] == ["en"]  # Russian voice, English text: accent
    r = client.get(f"/api/books/{bid}/languages", params={"voice": "en-ben-tucker"}).json()
    assert r["speakers"]["0"]["gaps"] == ["ru"]  # an English voice, Russian text
    r = client.get(f"/api/books/{bid}/languages", params={"voice": "russlib"}).json()
    assert r["speakers"]["0"]["gaps"] == ["en"]


def test_a_one_language_book_has_one_share_and_no_gaps(client):
    bid = upload(client, ("Глава 1\n\n" + RU + "\n\n" + RU).encode())
    r = client.get(f"/api/books/{bid}/languages", params={"voice": "en-ben-tucker"}).json()
    assert r["shares"] == {"ru": 1.0} and r["speakers"]["0"]["gaps"] == []


def test_the_chapter_text_names_the_stretches_in_another_language(client):
    bid = upload(client)
    blocks = client.get(f"/api/books/{bid}/text", params={"chapter": 0}).json()["blocks"]
    withlang = [b for b in blocks if b.get("langs")]
    assert withlang and withlang[0]["langs"][0][2] == "en"
    s, e, _ = withlang[0]["langs"][0]
    assert withlang[0]["text"][s:e] == "Good morning, everyone!"
    assert not [b for b in blocks if b["text"].startswith("Это длинный") and "langs" in b]


def test_a_speaker_with_a_voice_of_one_language_gets_the_gap(client):
    bid = upload(client)
    import json

    m = {"version": 1, "speakers": [{"id": 0, "name": "Narrator", "voice": ""},
                                    {"id": 1, "name": "Teacher", "voice": "en-ben-tucker"}],
         "chapters": {"0": {"spans": [{"b": 1, "s": 0, "e": len(MIX), "sp": 1, "tags": []}]}}}
    r = client.put(f"/api/books/{bid}/markup", content=json.dumps(m), headers={"Content-Type": "application/json"})
    assert r.status_code == 200, r.text
    got = client.get(f"/api/books/{bid}/languages").json()["speakers"]["1"]
    assert got["voice_lang"] == "en" and got["gaps"] == ["ru"]
