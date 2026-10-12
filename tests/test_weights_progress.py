import time

from folivox.tts import weights


def test_downloaded_counts_finished_and_incomplete_parts(tmp_path):
    (tmp_path / "llm.pt").write_bytes(b"x" * 100)
    (tmp_path / "other.bin").write_bytes(b"x" * 50)  # not in the patterns
    part = tmp_path / ".cache" / "huggingface" / "download"
    part.mkdir(parents=True)
    (part / "flow.pt.abc.incomplete").write_bytes(b"x" * 30)
    (part / "flow.pt.abc.metadata").write_bytes(b"x" * 9)  # not counted
    assert weights._downloaded(tmp_path, ["llm.pt", "flow.pt"]) == 130


def test_watch_reports_progress_and_final_total(tmp_path, monkeypatch):
    monkeypatch.setattr(weights, "_total_size", lambda patterns: 200)
    monkeypatch.setattr(weights, "POLL_SECONDS", 0.05)
    seen = []
    with weights.reporting(lambda name, done, total: seen.append((name, done, total))):
        with weights._watch("w", tmp_path, ["a.bin"]):
            (tmp_path / "a.bin").write_bytes(b"x" * 120)
            time.sleep(0.2)
    assert seen[0] == ("w", 0, 200) or seen[0][2] == 200
    assert seen[-1] == ("w", 200, 200)
    assert any(d == 120 for _, d, _ in seen)


def test_no_hook_is_silent(tmp_path):
    with weights._watch("w", tmp_path, ["a.bin"]):
        pass


def test_needs_download(tmp_path, monkeypatch):
    monkeypatch.delenv(weights.ENV, raising=False)
    monkeypatch.setattr(weights, "default_model_dir", lambda: tmp_path / "m")
    assert weights.needs_download(None, "rl")  # nothing there yet
    for f in weights.REQUIRED:
        (tmp_path / "m" / f).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "m" / f).write_bytes(b"x")
    assert not weights.needs_download(None, "base")
    assert weights.needs_download(None, "rl")  # the RL llm file is fetched separately
    (tmp_path / "m" / "llm.rl.pt").write_bytes(b"x")
    assert not weights.needs_download(None, "rl")
    assert not weights.needs_download(str(tmp_path / "custom"), "rl")  # user folders are never downloaded into


def test_watch_repo_reports_cache_growth(tmp_path, monkeypatch):
    from huggingface_hub import constants

    monkeypatch.setattr(constants, "HF_HUB_CACHE", str(tmp_path))
    monkeypatch.setattr(weights, "_repo_total", lambda repo: 300)
    monkeypatch.setattr(weights, "POLL_SECONDS", 0.05)
    blobs = tmp_path / "models--a--b" / "blobs"
    blobs.mkdir(parents=True)
    seen = []
    with weights.reporting(lambda name, done, total: seen.append((done, total))):
        with weights.watch_repo("asr", "a/b"):
            (blobs / "x.incomplete").write_bytes(b"x" * 100)
            time.sleep(0.2)
    assert any(d == 100 for d, _ in seen) and seen[-1] == (300, 300)


def test_watch_repo_without_hook_or_repo_is_silent():
    with weights.watch_repo("asr", "a/b"):
        pass
    with weights.reporting(lambda *a: None), weights.watch_repo("asr", None):
        pass
