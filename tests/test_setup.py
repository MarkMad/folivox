import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from folivox.cli import app

ROOT = Path(__file__).resolve().parent.parent


def test_setup_without_models_shows_machine_and_how_to_start():
    r = CliRunner().invoke(app, ["setup", "--skip-models"])
    if r.exit_code == 1:  # ffmpeg absent on this machine: must say how to fix it
        assert "ffmpeg is missing" in r.output
        return
    assert r.exit_code == 0, r.output
    for text in ("Hardware:", "folivox ui", "Ctrl+C", "folivox render", "folivox doctor"):
        assert text in r.output


def test_setup_download_failure_says_to_run_again(monkeypatch):
    from folivox.tts import weights

    def boom(*a, **k):
        raise RuntimeError("Downloading failed after 4 attempts")

    monkeypatch.setattr(weights, "resolve_model_dir", boom)
    r = CliRunner().invoke(app, ["setup"])
    if "ffmpeg is missing" in r.output:
        pytest.skip("ffmpeg not installed")
    assert r.exit_code == 1 and "again" in r.output


@pytest.mark.skipif(not shutil.which("bash") or sys.platform == "win32",
                    reason="no real bash (on Windows `bash` is the WSL stub)")
def test_install_script_is_valid_shell_and_documented():
    assert subprocess.run(["bash", "-n", str(ROOT / "scripts" / "install.sh")]).returncode == 0
    ps = (ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")
    sh = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
    for text in (sh, ps):  # both installers do the same five steps and end in `folivox setup`
        assert "uv tool install" in text and "folivox setup" in text and "ffmpeg" in text
    assert not any(line.strip().startswith("sudo ") for line in sh.splitlines())  # never runs with admin rights
