import json
import logging
import zipfile

from typer.testing import CliRunner

from folivox import diag
from folivox.cli import app
from folivox.journal import Journal
from folivox.text.chunk import Chunk

SECRET = "sk-proj-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"


def test_redact_keys_tokens_and_home(monkeypatch, tmp_path):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el-live-9f8e7d6c5b4a")
    text = (f"Authorization: Bearer {SECRET} api_key=abcdef123456 token: 'zzzzzzzz1' el-live-9f8e7d6c5b4a "
            "0123456789abcdef0123456789abcdef01 in /home/x")
    out = diag.redact(text)
    for leaked in (SECRET, "abcdef123456", "zzzzzzzz1", "el-live-9f8e7d6c5b4a", "0123456789abcdef0123456789abcdef01"):
        assert leaked not in out
    assert "/home/x" in out  # ordinary text is kept


def test_log_is_json_lines_with_traceback_and_no_secrets(tmp_path):
    f = tmp_path / "x.log"
    diag.setup_logging(f)
    try:
        raise RuntimeError(f"boom with {SECRET}")
    except RuntimeError:
        diag.event("job failed", level=logging.ERROR, exc_info=True, job="j1")
    for h in logging.getLogger(diag.LOGGER).handlers:
        h.flush()
    row = json.loads(f.read_text(encoding="utf-8").splitlines()[-1])
    assert row["msg"] == "job failed" and row["job"] == "j1" and "RuntimeError" in row["traceback"]
    assert SECRET not in f.read_text(encoding="utf-8")


def test_log_rotates(tmp_path):
    f = tmp_path / "r.log"
    diag.setup_logging(f)
    handlers = logging.getLogger(diag.LOGGER).handlers
    handlers[:] = [h for h in handlers if getattr(h, "baseFilename", "") == str(f)]  # a stray job thread may log
    handlers[0].maxBytes = 2000
    for i in range(200):
        diag.event("line", n=i, pad="x" * 50)
    assert len(list(tmp_path.glob("r.log*"))) > 1


def test_options_summary_hides_secrets_and_text():
    from pathlib import Path

    from folivox.pipeline import RenderOptions

    o = RenderOptions(output=Path("/a/b/book.m4b"), tts_description="a private description", tts="openai")
    s = diag.options_summary(o)
    assert s["output"] == "book.m4b" and "tts_description" not in s and s["tts"] == "openai"


def test_journal_summary_has_counts_not_text(tmp_path):
    j = Journal(tmp_path)
    chunk = Chunk(0, "SECRET SENTENCE", "SECRET SENTENCE", 0.3, "p")
    j.set_plan([("A very long chapter title that goes on and on and on", [chunk])], "v", "s")
    j.close()
    s = diag.journal_summary(tmp_path)
    assert s["fragments"] == 1 and s["fragments_done"] == 0
    assert "SECRET SENTENCE" not in json.dumps(s) and len(s["chapter_titles"][0]) <= 31


def test_support_bundle_is_a_redacted_zip(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    diag.setup_logging(diag.log_file())
    diag.event("note", key=f"Bearer {SECRET}")
    z = diag.support_bundle(tmp_path / "out" / "bundle.zip")
    with zipfile.ZipFile(z) as zf:
        assert set(zf.namelist()) == {"report.json", "folivox.log", "README.txt"}
        blob = "".join(zf.read(n).decode("utf-8") for n in zf.namelist())
    assert SECRET not in blob and "platform" in blob
    assert not list((tmp_path / "out").glob("*.part"))


def test_bundle_into_a_folder_names_the_file(tmp_path):
    z = diag.support_bundle(tmp_path)
    assert z.parent == tmp_path and z.suffix == ".zip"


def test_doctor_command(tmp_path):
    r = CliRunner().invoke(app, ["doctor", "--bundle", str(tmp_path)])
    assert r.exit_code == 0, r.output
    assert "ffmpeg" in r.output and "Support bundle" in r.output and list(tmp_path.glob("*.zip"))
