import subprocess

from test_uninstall import _setup

from folivox import uninstall


def test_symlinked_models_folder_removes_link_not_target(tmp_path, monkeypatch):
    data = _setup(tmp_path, monkeypatch)
    import shutil

    real = tmp_path / "elsewhere"
    shutil.move(str(data / "models"), real)
    (data / "models").symlink_to(real, target_is_directory=True)
    items = uninstall.plan()
    assert [i.size for i in items if i.path == data / "models"] == [0]
    assert uninstall.remove(items, everything=False) == []
    assert not (data / "models").exists() and (real / "Fun-CosyVoice3-0.5B" / "llm.pt").exists()


def test_install_sh_parses():
    assert subprocess.run(["bash", "-n", "scripts/install.sh"]).returncode == 0


def test_install_sh_failed_setup_dies_before_studio_offer():
    text = open("scripts/install.sh", encoding="utf-8").read()
    setup = text.index("folivox setup --skip-models || SETUP_RC=$?")
    check = text.index('[ "$SETUP_RC" = 0 ] || die', setup)
    assert check < text.index("Start the studio now?")
    assert "folivox doctor" in text[check : check + 300]


def test_install_sh_ffmpeg_hint_and_uv_dirs():
    text = open("scripts/install.sh", encoding="utf-8").read()
    for cmd in ("sudo dnf install ffmpeg", "sudo pacman -S ffmpeg", "sudo zypper install ffmpeg"):
        assert cmd in text
    assert text.index("XDG_BIN_HOME") < text.index("uv was installed but is not on PATH")
    assert text.index("UV_INSTALL_DIR") < text.index("uv was installed but is not on PATH")
