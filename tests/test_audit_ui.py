"""Audit regressions: cross-site requests, unreadable denoise uploads, empty audio in the denoiser."""

import numpy as np
import pytest

pytest.importorskip("starlette")
from starlette.testclient import TestClient  # noqa: E402

from folivox.ui.app import create_app  # noqa: E402


def client(tmp_path, **kw):
    return TestClient(create_app(data_dir=tmp_path, **kw))


def test_cross_site_origin_refused_without_token(tmp_path):
    c = client(tmp_path)
    r = c.put("/api/favorites", json=[], headers={"Origin": "http://evil.example"})
    assert r.status_code == 403
    assert c.post("/api/books/text", json={"text": "x"}, headers={"Origin": "null"}).status_code == 403
    assert c.get("/api/ping", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403


def test_same_origin_allowed(tmp_path):
    c = client(tmp_path)
    h = {"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"}
    assert c.get("/api/ping", headers=h).status_code == 200


def test_cross_site_refused_with_port(tmp_path):
    c = TestClient(create_app(data_dir=tmp_path, port=8765), base_url="http://127.0.0.1:8765")
    assert c.get("/api/ping", headers={"Origin": "http://127.0.0.1:8765"}).status_code == 200
    assert c.get("/api/ping", headers={"Origin": "http://localhost:9999"}).status_code == 403


def test_denoise_unreadable_is_415(tmp_path):
    r = client(tmp_path).post("/api/denoise", files={"file": ("x.webm", b"not audio", "audio/webm")})
    assert r.status_code == 415


def test_reduce_noise_empty():
    pytest.importorskip("noisereduce")
    from folivox.audio.denoise import reduce_noise

    assert len(reduce_noise(np.zeros(0, dtype=np.float32), 16000)) == 0
