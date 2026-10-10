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
