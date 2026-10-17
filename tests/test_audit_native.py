"""Audit regressions: failed native server starts and failed Fish worker loads clean up after themselves."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from folivox.tts import fish, native, native_setup


def test_native_start_failure_removes_tmp_and_reaps(tmp_path, monkeypatch):
    monkeypatch.setenv(native_setup.DIR_ENV, str(tmp_path))
    monkeypatch.setattr(native, "server_command", lambda s: [sys.executable, "-c", "raise SystemExit(3)"])
    s = native.Server(native.Spec(tmp_path / "srv", tmp_path / "m.gguf", "cpu"))
    with pytest.raises(native_setup.NativeError):
        s.start()
    assert s.proc is None and s._tmp is None


def test_native_popen_failure_removes_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv(native_setup.DIR_ENV, str(tmp_path))
    monkeypatch.setattr(native, "server_command", lambda s: [str(tmp_path / "missing binary")])
    s = native.Server(native.Spec(tmp_path / "srv", tmp_path / "m.gguf", "cpu"))
    with pytest.raises(native_setup.NativeError):
        s.start()
    assert s._tmp is None


def test_fish_failed_load_drops_worker(tmp_path, monkeypatch):
    class W:
        closed = False

        def __init__(self, python):
            pass

        def call(self, req, timeout):
            raise fish.FishError("load failed")

        def close(self):
            W.closed = True

    eng = object.__new__(fish.FishEngine)
    eng.native, eng._worker, eng._refs = False, None, {}
    eng.build = SimpleNamespace(runtime="rt", kind="s2")
    monkeypatch.setattr(fish, "_Worker", W)
    monkeypatch.setattr(fish.fish_setup, "venv_python", lambda rt: Path("py"))
    monkeypatch.setattr(fish.builds, "weights_dir", lambda b: tmp_path)
    monkeypatch.setattr(eng, "_reference", lambda v: tmp_path / "r.wav", raising=False)
    with pytest.raises(fish.FishError):
        eng.start(SimpleNamespace(transcript="t"))
    assert eng._worker is None and W.closed


def test_build_and_setup_steps_time_out(monkeypatch):
    from folivox.tts import fish_setup, native_build

    monkeypatch.setattr(native_build, "RUN_TIMEOUT", 0.2)
    monkeypatch.setattr(fish_setup, "RUN_TIMEOUT", 0.2)
    slow = [sys.executable, "-c", "import time; time.sleep(5)"]
    with pytest.raises(native_setup.NativeError, match="did not finish"):
        native_build._run(slow, None, "Step", lambda m: None)
    with pytest.raises(fish_setup.InstallError, match="did not finish"):
        fish_setup._run(slow, "Step", lambda m: None)
    with pytest.raises(fish_setup.InstallError, match="could not start"):
        fish_setup._run(["/nonexistent/tool"], "Step", lambda m: None)
