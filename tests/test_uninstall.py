
from folivox import uninstall
from folivox.tts import weights


def _setup(tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setattr(uninstall, "data_dir", lambda: data)
    monkeypatch.setattr(uninstall, "user_config_dir", lambda *a, **k: str(tmp_path / "cfg"))
    monkeypatch.setattr(weights, "user_data_dir", lambda *a, **k: str(data))
    monkeypatch.setattr("folivox.config.config_path", lambda: tmp_path / "cfg" / "config.toml")
    monkeypatch.delenv("FOLIVOX_CONFIG", raising=False)
    from huggingface_hub import constants

    monkeypatch.setattr(constants, "HF_HUB_CACHE", str(tmp_path / "hub"))
    for p in ("models/Fun-CosyVoice3-0.5B/llm.pt", "voices/me/a.wav", "ui/state.json", "ui_token"):
        (data / p).parent.mkdir(parents=True, exist_ok=True)
        (data / p).write_bytes(b"x" * 10)
    (tmp_path / "cfg").mkdir()
    (tmp_path / "cfg" / "config.toml").write_text("a=1")
    return data


def test_whisper_claimed_only_when_not_there_before(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    weights._claim_repo("a/new")
    (tmp_path / "hub" / "models--a--old").mkdir(parents=True)
    weights._claim_repo("a/old")
    assert weights.owned_repos() == ["a/new"]


def test_default_plan_removes_models_and_owned_whisper_only(tmp_path, monkeypatch):
    data = _setup(tmp_path, monkeypatch)
    weights._claim_repo("a/new")
    (tmp_path / "hub" / "models--a--new").mkdir(parents=True)
    (tmp_path / "hub" / "models--a--new" / "f").write_bytes(b"x")
    (tmp_path / "hub" / "models--b--theirs").mkdir()  # user's own, never claimed
    items = uninstall.plan()
    assert {i.path for i in items} == {data / "models", tmp_path / "hub" / "models--a--new"}
    assert uninstall.remove(items, everything=False) == []
    assert (data / "voices").exists() and (tmp_path / "cfg" / "config.toml").exists()
    assert (tmp_path / "hub" / "models--b--theirs").exists()
    assert weights.owned_repos() == []


def test_everything_adds_voices_settings_and_tidies(tmp_path, monkeypatch):
    data = _setup(tmp_path, monkeypatch)
    items = uninstall.plan(everything=True)
    assert uninstall.remove(items, everything=True) == []
    assert not data.exists() and not (tmp_path / "cfg").exists()


def test_user_config_from_env_is_never_planned(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    monkeypatch.setenv("FOLIVOX_CONFIG", str(tmp_path / "cfg" / "config.toml"))
    assert all(i.label != "Settings" for i in uninstall.plan(everything=True))
