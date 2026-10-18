"""API keys from ``NAME_FILE`` (Docker secrets): reading, priority, errors, redaction."""

from __future__ import annotations

import pytest

from folivox import config, diag

KEY = "sk-test-0123456789abcdef"


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for n in ("OPENAI_API_KEY", "OPENAI_API_KEY_FILE"):
        monkeypatch.delenv(n, raising=False)
    monkeypatch.setattr(config, "keychain_get", lambda name: None)
    monkeypatch.setattr(diag, "_KNOWN_SECRETS", set())


def test_key_from_file_is_trimmed(monkeypatch, tmp_path):
    f = tmp_path / "openai"
    f.write_text(f"  {KEY}\n\n")
    monkeypatch.setenv("OPENAI_API_KEY_FILE", str(f))
    assert config.api_key("OPENAI_API_KEY", "OpenAI") == KEY
    assert config.env_key_set("OPENAI_API_KEY")


def test_explicit_variable_wins_over_the_file(monkeypatch, tmp_path):
    f = tmp_path / "openai"
    f.write_text("from-the-file-123456")
    monkeypatch.setenv("OPENAI_API_KEY_FILE", str(f))
    monkeypatch.setenv("OPENAI_API_KEY", KEY)
    assert config.api_key("OPENAI_API_KEY", "OpenAI") == KEY


def test_empty_or_missing_file_is_a_clear_error_without_the_value(monkeypatch, tmp_path):
    f = tmp_path / "openai"
    f.write_text(" \n")
    monkeypatch.setenv("OPENAI_API_KEY_FILE", str(f))
    with pytest.raises(ValueError, match="is empty"):
        config.api_key("OPENAI_API_KEY", "OpenAI")
    monkeypatch.setenv("OPENAI_API_KEY_FILE", str(tmp_path / "nope"))
    with pytest.raises(ValueError, match="cannot read"):
        config.api_key("OPENAI_API_KEY", "OpenAI")


def test_nothing_set_names_both_ways_to_give_the_key():
    with pytest.raises(ValueError, match="OPENAI_API_KEY_FILE"):
        config.api_key("OPENAI_API_KEY", "OpenAI")
    assert not config.env_key_set("OPENAI_API_KEY")


def test_support_bundle_redacts_a_key_from_a_file(monkeypatch, tmp_path):
    f = tmp_path / "openai"
    f.write_text(KEY)
    monkeypatch.setenv("OPENAI_API_KEY_FILE", str(f))
    monkeypatch.setattr(diag, "_secret_names", lambda providers=True: {"OPENAI_API_KEY"})
    diag.remember_secrets(keychain=False)
    assert KEY not in diag.redact(f"Authorization failed for {KEY}")


def test_studio_shows_a_file_key_as_set(monkeypatch, tmp_path):
    pytest.importorskip("starlette")
    pytest.importorskip("multipart")
    from starlette.testclient import TestClient

    from folivox.ui.app import create_app

    f = tmp_path / "openai"
    f.write_text(KEY)
    monkeypatch.setenv("OPENAI_API_KEY_FILE", str(f))
    c = TestClient(create_app(token="t" * 20, port=8765, data_dir=tmp_path / "ui"), base_url="http://127.0.0.1:8765",
                   headers={"X-Folivox-Token": "t" * 20})
    r = c.get("/api/keys")
    assert r.status_code == 200 and KEY not in r.text
    assert any(k["name"] == "OPENAI_API_KEY" and k["env"] for k in r.json()["keys"])
