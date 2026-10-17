import json
import sys
import zipfile
from pathlib import Path

from folivox import bench, config, diag


def test_keychain_only_key_of_any_format_is_redacted(monkeypatch, tmp_path):
    odd = "q7Z!w_odd"  # matches none of the generic key patterns
    monkeypatch.setattr(diag, "_KNOWN_SECRETS", set())
    monkeypatch.setattr(diag, "_secret_names", lambda providers=True: {"CUSTOM_LLM_CRED"})
    monkeypatch.delenv("CUSTOM_LLM_CRED", raising=False)
    monkeypatch.setattr(config, "keychain_get", lambda n: odd if n == "CUSTOM_LLM_CRED" else None)
    diag.remember_secrets()
    out = diag.redact(f"failed with {odd} and {json.dumps(odd + chr(34))}")
    assert odd not in out


def test_custom_api_key_env_names_come_from_config(monkeypatch):
    monkeypatch.setattr(config, "load", lambda: {"llm": {"openai": {"api_key_env": "MY_CRED"}}})
    assert "MY_CRED" in diag._secret_names(providers=False)


def test_username_in_other_paths_is_redacted():
    user = Path.home().name
    if len(user) < 3:
        return
    out = diag.redact(f"/Volumes/data/{user}/books/x.epub")
    assert f"/{user}/" not in out


def test_report_survives_broken_torch(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", None)  # import torch -> ImportError
    assert diag.devices() == {"torch": None}
    assert diag.hardware()["device"] is None


def test_bench_report_with_broken_native_manifest(monkeypatch):
    from folivox.tts import native_setup

    monkeypatch.setattr(native_setup, "load", lambda: (_ for _ in ()).throw(ValueError("bad manifest")))
    text = bench.report_text([{"device": "cpu", "error": "boom"}], "cosyvoice3", "en")
    assert "unknown" in text and "FAILED boom" in text


def test_bundle_has_no_keychain_secret(monkeypatch, tmp_path):
    odd = "zz-keychain-only-77"
    monkeypatch.setattr(diag, "_KNOWN_SECRETS", set())
    monkeypatch.setattr(diag, "_secret_names", lambda providers=True: {"X_CRED"})
    monkeypatch.setattr(config, "keychain_get", lambda n: odd)
    log = tmp_path / "f.log"
    log.write_text(f'{{"msg": "bad {odd}"}}\n', encoding="utf-8")
    monkeypatch.setattr(diag, "log_file", lambda: log)
    z = diag.support_bundle(tmp_path / "b.zip")
    with zipfile.ZipFile(z) as f:
        assert all(odd not in f.read(n).decode() for n in f.namelist())
