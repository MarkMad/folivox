"""Audit regressions: weights completeness, progress watcher races, reuse roots, config parsing."""

from pathlib import Path

import pytest

from folivox import config
from folivox.tts import reuse, weights


def test_partial_blanken_is_not_complete(tmp_path):
    for f in weights.REQUIRED:
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / f).write_bytes(b"x")
    assert weights.is_complete(tmp_path)
    (tmp_path / "CosyVoice-BlankEN/model.safetensors").unlink()  # interrupted snapshot: config.json landed first
    assert not weights.is_complete(tmp_path)


def test_downloaded_survives_vanishing_file(tmp_path, monkeypatch):
    (tmp_path / "llm.pt").write_bytes(b"abc")
    real = Path.stat

    def flaky(self, *a, **k):
        if self.name == "llm.pt" and flaky.armed:
            flaky.armed = False
            return real(self, *a, **k)  # is_file
        if self.name == "llm.pt":
            raise FileNotFoundError(self)
        return real(self, *a, **k)

    flaky.armed = True
    monkeypatch.setattr(Path, "stat", flaky)
    assert weights._downloaded(tmp_path, ["llm.pt"]) == 0


def test_hf_roots_expand_and_follow_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("HF_HOME", "~/hfhome")
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    roots = reuse.hf_cache_roots()
    assert Path("~/hfhome").expanduser() / "hub" in roots
    assert tmp_path / "huggingface" / "hub" in roots


def test_bad_toml_names_the_file(tmp_path, monkeypatch):
    p = tmp_path / "config.toml"
    p.write_text("[providers\n", encoding="utf-8")
    monkeypatch.setenv("FOLIVOX_CONFIG", str(p))
    config.load.cache_clear()
    with pytest.raises(ValueError, match="config.toml"):
        config.load()
    config.load.cache_clear()


def test_save_runtime_over_scalar_runtime(tmp_path, monkeypatch):
    pytest.importorskip("tomli_w")
    p = tmp_path / "config.toml"
    p.write_text('runtime = "native"\n', encoding="utf-8")
    monkeypatch.setenv("FOLIVOX_CONFIG", str(p))
    config.load.cache_clear()
    config.save_runtime("pytorch")
    assert config.runtime() == "pytorch"
    config.load.cache_clear()


def test_with_retries_does_not_retry_permanent_hub_errors():
    errors = pytest.importorskip("huggingface_hub.errors")
    calls, sleeps = [], []

    def fn():
        calls.append(1)
        raise errors.RepositoryNotFoundError("no such repo")

    with pytest.raises(errors.RepositoryNotFoundError):
        weights.with_retries(fn, "x", sleep=sleeps.append)
    assert len(calls) == 1 and not sleeps
