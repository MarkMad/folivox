"""Decided fixes: removal refused while a job runs, non-object JSON bodies, runtime-aware Fish recommendation."""

import dataclasses

import pytest

pytest.importorskip("starlette")
from starlette.testclient import TestClient  # noqa: E402

from folivox.tts import builds  # noqa: E402
from folivox.tts.builds import Hardware  # noqa: E402
from folivox.ui.app import create_app  # noqa: E402

TOKEN = "t"
MAC_64 = Hardware("darwin", "arm64", 64.0, 50.0)


def _client(tmp_path):
    app = create_app(token=TOKEN, port=8765, data_dir=tmp_path / "ui", render=lambda *a: None)
    return app, TestClient(app, base_url="http://127.0.0.1:8765", headers={"X-Folivox-Token": TOKEN})


def test_remove_refused_while_job_runs(tmp_path, monkeypatch):
    from folivox.tts import fish_setup, native, native_setup

    app, c = _client(tmp_path)
    called = []
    monkeypatch.setattr(native, "shutdown_all", lambda: called.append("shutdown"))
    monkeypatch.setattr(native_setup, "remove", lambda: called.append("rm") or 0)
    monkeypatch.setattr(fish_setup, "remove", lambda b: called.append("fish") or 0)
    monkeypatch.setattr(app.state.ui.manager, "busy", lambda: True)
    bid = builds.load().builds[0].id
    for url, body in (("/api/runtime/remove", None), ("/api/engines/fish/remove", {"build": bid})):
        r = c.post(url, json=body) if body else c.post(url)
        assert r.status_code == 409 and r.json()["code"] == "job_busy"
    assert called == []


def test_non_object_json_is_400(tmp_path):
    _, c = _client(tmp_path)
    for method, url in (("PUT", "/api/runtime"), ("POST", "/api/engines/fish/remove"),
                        ("POST", "/api/engines/fish/install"), ("POST", "/api/engines/fish/accept"),
                        ("POST", "/api/engines/fish/revoke")):
        r = c.request(method, url, json=[1, 2])
        assert r.status_code == 400, (url, r.status_code)


def test_recommend_matches_runtime(monkeypatch):
    cat = builds.load()
    native = dataclasses.replace(cat.build("s2pro-native-q8"), status="verified", rank=10_000)
    cat2 = dataclasses.replace(cat, builds=[native if b.id == native.id else b for b in cat.builds])
    monkeypatch.setattr(builds, "supported_here", lambda b, hw, cat=None: True)
    accepted = {k: {"version": v.version, "sha256": v.text_sha256} for k, v in cat.licences.items()}
    everything = lambda b: True  # noqa: E731
    only_native = lambda b: b.backend == "native"  # noqa: E731
    # PyTorch runtime: a native build is never the default, even the top-ranked installed one
    assert builds.recommend(MAC_64, accepted, everything, cat2, runtime="pytorch").backend != "native"
    assert builds.recommend(MAC_64, accepted, only_native, cat2, runtime="pytorch") is None
    # native runtime: only the native build, and only when installed
    assert builds.recommend(MAC_64, accepted, everything, cat2, runtime="native").id == native.id
    assert builds.recommend(MAC_64, accepted, lambda b: b.backend != "native", cat2, runtime="native") is None


def test_book_warnings_reach_summary_and_library(tmp_path):
    from types import SimpleNamespace

    from folivox.ui.app import _book_summary

    book = SimpleNamespace(title="T", author="", lang="ru", source_format="txt", year="", cover=None, chars=1,
                           estimated_seconds=1, warnings=["lang_uk"], chapters=lambda depth: [])
    assert _book_summary("b", book)["warnings"] == ["lang_uk"]
    _, c = _client(tmp_path)
    text = "Це українська книга. Вона має багато слів, які пишуться через і та ї, тому її легко впізнати.\n" * 20
    r = c.post("/api/books", files={"file": ("uk.txt", text.encode(), "text/plain")})
    assert r.status_code == 200, r.text
    got = r.json()["warnings"]
    assert got == ["lang_uk"]
    listed = next(b for b in c.get("/api/books").json()["books"] if b["book_id"] == r.json()["book_id"])
    assert listed["warnings"] == got
