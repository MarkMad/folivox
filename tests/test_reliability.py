"""Failure handling with fakes: no network, no models, no paid calls."""
import shutil
from pathlib import Path

import numpy as np
import pytest
from test_cloud import Fake, ok, wav_bytes
from test_cloud_tts import engine

from folivox.audio import audio_seconds, save
from folivox.journal import Journal, Take
from folivox.pipeline import Cancelled, Events, RenderOptions, _chapter_ok, load_engine, preflight
from folivox.text.chunk import Chunk
from folivox.tts import weights
from folivox.tts.cloud import CloudVoice
from folivox.voicegen.cloud import CloudError

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


def tone(seconds=1.0, sr=24000):
    return (0.2 * np.sin(np.linspace(0, 440 * seconds * 6.28, int(sr * seconds)))).astype(np.float32)


def journal_with_take(tmp_path, audio_ok=True):
    j = Journal(tmp_path)
    j.set_plan([("Ch", [Chunk(0, "a", "a", 0.3, "p")])], "v", "s")
    key = j.pending()[0].key
    if audio_ok:
        save(j.audio_path(key), tone(1.0), 24000)
    else:
        j.audio_path(key).write_bytes(b"")
    j.record(Take(key, 1.0, 0.0, "a", 1, 1.0))
    return j, key


# --- journal / crash recovery ---------------------------------------------------------------------
def test_empty_audio_file_is_not_done(tmp_path):
    j, key = journal_with_take(tmp_path, audio_ok=False)
    assert not j.is_done(key) and [c.key for c in j.pending()] == [key]


def test_audit_keeps_good_and_drops_damaged_takes(tmp_path):
    j, key = journal_with_take(tmp_path)
    assert j.audit() == [] and j.is_done(key)
    j.audio_path(key).write_bytes(b"not a flac at all" * 50)  # torn write after power loss
    assert j.audit() == [key]
    assert not j.audio_path(key).exists() and [c.key for c in j.pending()] == [key]


def test_audit_catches_truncated_audio(tmp_path):
    j, key = journal_with_take(tmp_path)
    save(j.audio_path(key), tone(0.2), 24000)  # shorter than recorded 1.0 s
    assert j.audit() == [key]


def test_chapter_cache_is_validated_by_duration(tmp_path):
    f = tmp_path / "001.flac"
    save(f, tone(2.0), 24000)
    assert _chapter_ok(f, 2.0) and not _chapter_ok(f, 9.0) and not _chapter_ok(f, None)
    f.write_bytes(b"junk")
    assert not _chapter_ok(f, 2.0) and audio_seconds(f) is None
    assert not _chapter_ok(tmp_path / "missing.flac", 2.0)


# --- final assemble --------------------------------------------------------------------------------
@needs_ffmpeg
def test_failed_encode_keeps_the_earlier_book(tmp_path, monkeypatch):
    from folivox.audio import assemble as asm

    ch = tmp_path / "c.flac"
    save(ch, tone(1.0), 24000)
    chapters = [asm.ChapterAudio("One", ch, 1.0)]
    out = tmp_path / "book.m4b"
    asm.write_m4b(chapters, out, asm.BookMeta("T"))
    good = out.read_bytes()
    assert good and not list(tmp_path.glob("*.part"))

    def boom(args):
        Path(args[-1]).write_bytes(b"half")
        raise RuntimeError("ffmpeg failed: no space left on device")

    monkeypatch.setattr(asm, "run", boom)
    with pytest.raises(RuntimeError):
        asm.write_m4b(chapters, out, asm.BookMeta("T"))
    assert out.read_bytes() == good and not list(tmp_path.glob("*.part"))


def test_ffmpeg_missing_is_reported_before_synthesis(tmp_path, monkeypatch):
    from folivox.audio import assemble as asm

    monkeypatch.delenv("FOLIVOX_FFMPEG", raising=False)
    monkeypatch.setattr(asm.shutil, "which", lambda *a, **k: None)
    with pytest.raises(asm.FFmpegMissing, match="Install it"):
        preflight(RenderOptions(output=tmp_path / "b.m4b"), Events())


def test_unwritable_output_folder_is_reported_early(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")  # a file where a folder is needed
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    with pytest.raises(RuntimeError, match="Cannot write"):
        preflight(RenderOptions(output=blocker / "sub" / "b.m4b"), Events())


def test_safe_names_work_on_windows_and_cyrillic():
    from folivox.audio.assemble import safe_name

    assert safe_name('Глава 1: «Начало»?') == "Глава 1 «Начало»"
    assert safe_name("The end...  ") == "The end"
    assert safe_name("a/b\\c|d") == "abcd"


def test_work_dir_expands_tilde():
    o = RenderOptions(output=Path("x.m4b"), work_dir=Path("~/folivox-work"))
    assert "~" not in str(o.resolved_work_dir())


# --- local model -----------------------------------------------------------------------------------
def test_gpu_load_failure_falls_back_to_cpu(monkeypatch):
    tried = []

    class Eng:
        device = "cpu"

    def create(name, **opts):
        tried.append(opts["device"])
        if opts["device"] != "cpu":
            raise RuntimeError("MPS backend out of memory")
        return Eng()

    from folivox.tts import ENGINES

    monkeypatch.setattr(ENGINES, "create", create)
    warnings = []

    class Ev(Events):
        def warning(self, m):
            warnings.append(m)

    assert isinstance(load_engine(RenderOptions(output=Path("b.m4b"), device="mps"), Ev()), Eng)
    assert tried == ["mps", "cpu"] and "CPU" in warnings[0]


def test_load_failure_everywhere_has_a_clear_message(monkeypatch):
    from folivox.tts import ENGINES

    def create(name, **opts):
        raise RuntimeError("corrupt checkpoint")

    monkeypatch.setattr(ENGINES, "create", create)
    with pytest.raises(RuntimeError, match="Could not load.*corrupt checkpoint.*weights"):
        load_engine(RenderOptions(output=Path("b.m4b"), device="cpu"), Events())


def test_empty_weight_file_means_incomplete(tmp_path):
    for f in weights.REQUIRED:
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / f).write_bytes(b"x")
    assert weights.is_complete(tmp_path)
    (tmp_path / "flow.pt").write_bytes(b"")  # interrupted copy
    assert not weights.is_complete(tmp_path)


def test_download_retries_then_succeeds_and_reports_failure(monkeypatch):
    waits, calls = [], []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("reset")
        return "ok"

    assert weights.with_retries(flaky, "w", sleep=waits.append) == "ok" and len(waits) == 2
    with pytest.raises(RuntimeError, match="failed after 2 attempts.*continues"):
        weights.with_retries(lambda: (_ for _ in ()).throw(ConnectionError("down")), "w", attempts=2,
                             sleep=lambda s: None)
    with pytest.raises(RuntimeError, match="No space left"):
        weights.with_retries(lambda: (_ for _ in ()).throw(OSError(28, "full")), "w", sleep=lambda s: None)


# --- cloud outage ----------------------------------------------------------------------------------
VOICE = CloudVoice("openai", "gpt-4o-mini-tts", "coral")


def test_outage_is_waited_out_and_billed_once():
    down = CloudError("Cannot reach the provider: down", "network")
    eng, fake = engine(fake=Fake(down, down, ok(wav_bytes())))
    eng.gen.retries = 0
    eng.sleep, notes = (lambda s: None), []
    eng.on_wait = notes.append
    wav, _ = eng.prepare("Hello there.", VOICE)
    assert wav and len(fake.calls) == 3 and len(notes) == 2
    assert eng.chars_sent == len("Hello there.") and eng.requests == 1


def test_long_outage_gives_up_with_a_resume_hint():
    eng, fake = engine(fake=Fake(CloudError("Cannot reach the provider: down", "network")))
    eng.gen.retries = 0
    eng.sleep, eng.outage_seconds, eng.wait_for = (lambda s: None), 60, 30
    with pytest.raises(CloudError, match="run the same command again"):
        eng.prepare("Hello there.", VOICE)


def test_cancel_during_outage_stops_waiting():
    eng, fake = engine(fake=Fake(CloudError("Cannot reach the provider: down", "network")))
    eng.gen.retries = 0
    eng.sleep, eng.should_stop = (lambda s: None), (lambda: True)
    with pytest.raises(CloudError):
        eng.prepare("Hello there.", VOICE)
    assert len(fake.calls) == 1


def test_auth_error_is_not_retried_and_not_billed():
    eng, fake = engine(fake=Fake(ok({"error": {"message": "bad"}}, status=401)))
    eng.sleep = lambda s: None
    with pytest.raises(CloudError) as e:
        eng.prepare("Hello there.", VOICE)
    assert e.value.kind == "auth" and len(fake.calls) == 1 and eng.chars_sent == 0


def test_cap_is_checked_before_the_request():
    from folivox.tts.cloud import CostCapReached

    eng, fake = engine(max_cost=0.0001)
    with pytest.raises(CostCapReached):
        eng.prepare("x" * 3000, VOICE)
    assert fake.calls == [] and eng.chars_sent == 0


def test_cancel_exception_exists_for_pipeline():
    assert issubclass(Cancelled, Exception)
