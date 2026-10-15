"""Studio routes of the automatic markup, with a fake language model."""

import time

import pytest

pytest.importorskip("starlette")
pytest.importorskip("httpx")

from starlette.testclient import TestClient  # noqa: E402
from test_markup_llm import P1, P2, P3, P4, P5, FakeLLM  # noqa: E402

from folivox import config  # noqa: E402
from folivox.ui.app import create_app  # noqa: E402

TOKEN = "t0ken"
BOOK = ("Глава 1\n\n" + "\n\n".join((P1, P2, P3, P4)) + "\n\nГлава 2\n\n" + P5 + "\n").encode()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FOLIVOX_CONFIG", str(tmp_path / "config.toml"))
    config.load.cache_clear()
    holder = {"llm": FakeLLM()}
    app = create_app(token=TOKEN, port=8765, data_dir=tmp_path / "ui", render=lambda b, o, e: o.output,
                     services={"llm": lambda name: holder["llm"]})
    c = TestClient(app, base_url="http://127.0.0.1:8765", headers={"X-Folivox-Token": TOKEN})
    c.holder = holder
    yield c
    config.load.cache_clear()


def upload(client):
    r = client.post("/api/books", files={"file": ("tale.txt", BOOK, "text/plain")})
    return r.json()["book_id"]


def wait(client, bid):
    for _ in range(200):
        st = client.get(f"/api/books/{bid}/llm/status").json()
        if st["state"] != "running":
            return st
        time.sleep(0.05)
    raise AssertionError("the task did not finish")


def test_models_route_lists_gemma_tiers(client):
    m = client.get("/api/llm/models").json()
    assert m["recommended"].startswith("gemma4:") and len(m["tiers"]) == 5


def test_analyse_then_auto_then_edit_characters(client):
    bid = upload(client)
    assert client.get(f"/api/books/{bid}/characters").json()["characters"] == []
    assert client.post(f"/api/books/{bid}/llm/start", json={"task": "nope"}).status_code == 400
    assert client.post(f"/api/books/{bid}/llm/start", json={"task": "analyse"}).status_code == 202
    st = wait(client, bid)
    assert st["state"] == "done" and "voices needed" in st["message"]
    bible = client.get(f"/api/books/{bid}/characters").json()
    assert {c["name"] for c in bible["characters"]} == {"Анна", "Борис"} and bible["voices_needed"] >= 1
    assert client.post(f"/api/books/{bid}/llm/start", json={"task": "auto"}).status_code == 202
    st = wait(client, bid)
    assert st["state"] == "done" and st["stats"]["marked"] == 3
    mk = client.get(f"/api/books/{bid}/markup").json()
    assert mk["chapters"] and {s["name"] for s in mk["speakers"]} >= {"Анна", "Борис"}
    bible["characters"][0]["name"] = "Анна Сергеевна"
    saved = client.put(f"/api/books/{bid}/characters", json=bible).json()
    assert saved["characters"][0]["name"] == "Анна Сергеевна"
    bible["characters"][0]["id"] = 40
    assert client.put(f"/api/books/{bid}/characters", json=bible).status_code == 400


def test_model_failure_is_reported_not_raised(client):
    bid = upload(client)
    client.holder["llm"] = FakeLLM("down")
    client.post(f"/api/books/{bid}/llm/start", json={"task": "analyse"})
    st = wait(client, bid)
    assert st["state"] == "error" and "did not answer" in st["message"]
