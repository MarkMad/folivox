"""Decided fixes: the RL LLM file never lands in a user folder; `folivox update` in a dev checkout."""
import sys
import types
from pathlib import Path

import pytest

from folivox.tts import weights


def _complete(d: Path) -> Path:
    for f in weights.REQUIRED:
        (d / f).parent.mkdir(parents=True, exist_ok=True)
        (d / f).write_bytes(b"x")
    return d


@pytest.fixture
def own(tmp_path, monkeypatch):
    d = tmp_path / "own"
    monkeypatch.setattr(weights, "default_model_dir", lambda: d)
    monkeypatch.delenv(weights.ENV, raising=False)
    calls = []

    def fake_dl(repo, name, local_dir):
        calls.append(Path(local_dir))
        (Path(local_dir) / name).write_bytes(b"rl")

    monkeypatch.setitem(sys.modules, "huggingface_hub", types.SimpleNamespace(hf_hub_download=fake_dl))
    return d, calls


def test_user_folder_without_rl_uses_own_copy(tmp_path, own):
    d, calls = own
    user = _complete(tmp_path / "user")
    assert weights.needs_download(str(user), "rl")
    rel = weights.ensure_llm(user, "rl")
    assert calls == [d]  # downloaded into Folivox's own folder only
    assert not (user / "llm.rl.pt").exists()
    assert Path(f"{user}/{rel}").resolve() == (d / "llm.rl.pt").resolve()  # how CosyVoice3 joins it
    assert not weights.needs_download(str(user), "rl")
    calls.clear()
    weights.ensure_llm(user, "rl")
    assert calls == []


def test_user_folder_with_rl_and_default_unchanged(tmp_path, own):
    d, calls = own
    user = _complete(tmp_path / "user")
    (user / "llm.rl.pt").write_bytes(b"rl")
    assert not weights.needs_download(str(user), "rl")
    assert weights.ensure_llm(user, "rl") == "llm.rl.pt"
    assert not weights.needs_download(str(user), "base")
    _complete(d)
    assert weights.needs_download(None, "rl")
    assert weights.ensure_llm(d, "rl") == "llm.rl.pt" and calls == [d]
    assert not weights.needs_download(None, "rl")


def test_incomplete_user_folder_is_not_reported_as_download(tmp_path, own):
    assert not weights.needs_download(str(tmp_path / "nothing"), "rl")


def test_update_refuses_in_dev_checkout(monkeypatch):
    from typer.testing import CliRunner

    from folivox import cli

    monkeypatch.setattr(cli, "_dev_checkout", lambda: True)
    res = CliRunner().invoke(cli.app, ["update", "--yes"])
    assert res.exit_code == 1 and "git pull" in res.output


def test_update_reports_missing_shell(monkeypatch):
    import subprocess
    import urllib.request

    from typer.testing import CliRunner

    from folivox import cli

    monkeypatch.setattr(cli, "_dev_checkout", lambda: False)
    monkeypatch.setattr(sys, "platform", "linux")

    class R:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"echo hi"

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: R())

    def boom(*a, **k):
        raise FileNotFoundError("bash")

    monkeypatch.setattr(subprocess, "call", boom)
    res = CliRunner().invoke(cli.app, ["update", "--yes"])
    assert res.exit_code == 1 and "Could not start" in res.output
