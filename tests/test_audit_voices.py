"""Audit checks for the voice catalog, voice generation and the Qwen worker."""

import ast
import json
import sys
from pathlib import Path

import pytest

import folivox.voices as voices
from folivox.voicegen import Job, Qwen3TTS
from folivox.voices.design import safe_texts


def test_catalog_matches_flac_files():
    entries = voices.bundled()
    ids = [v.id for v in entries]
    assert len(ids) == len(set(ids))
    assert {p.stem for p in voices.PACKAGE_DIR.glob("*.flac")} == set(ids)
    for v in entries:
        assert v.path.is_file() and v.transcript.strip() and v.gender in ("f", "m") and v.license
        assert not v.commercial


def test_safe_texts_cover_book_languages():
    for lang in ("ru", "en", "de", "fr", "es", "it", "zh", "ja", "ko"):
        assert safe_texts(lang)


def test_qwen_worker_does_not_import_folivox():
    tree = ast.parse((Path(voices.__file__).parents[1] / "voicegen" / "qwen_worker.py").read_text("utf-8"))
    names = [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    names += [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert not any(m.split(".")[0] == "folivox" for m in names)


def test_broken_user_meta_does_not_hide_other_voices(tmp_path, monkeypatch):
    monkeypatch.setattr(voices, "user_voices_dir", lambda: tmp_path)
    (tmp_path / "bad").mkdir()
    (tmp_path / "bad" / "meta.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "extra").mkdir()
    (tmp_path / "extra" / "meta.json").write_text(json.dumps({"id": "extra", "unknown": 1}), encoding="utf-8")
    good = voices.VoiceEntry("good", "Good", "f", "en", "Hello there.")
    (tmp_path / "good").mkdir()
    (tmp_path / "good" / "meta.json").write_text(json.dumps(good.to_meta()), encoding="utf-8")
    assert [v.id for v in voices.user()] == ["good"]


def test_qwen_worker_is_killed_when_progress_cancels(tmp_path):
    fake = tmp_path / "fake.py"
    fake.write_text("import json,sys,time\nreq=json.load(sys.stdin)\n"
                    "for j in req['jobs']:\n print(json.dumps({'out': j['out'], 'seconds': 1}), flush=True)\n"
                    "time.sleep(60)\n", encoding="utf-8")
    gen = Qwen3TTS(str(tmp_path), python=sys.executable)
    import folivox.voicegen as vg

    orig = vg.Path.with_name
    procs = []
    real_popen = vg.subprocess.Popen

    def popen(cmd, **kw):
        p = real_popen([cmd[0], str(fake)], **kw)
        procs.append(p)
        return p

    class Stop(Exception):
        pass

    def progress(job, seconds):
        raise Stop

    vg.subprocess.Popen, saved = popen, vg.subprocess.Popen
    try:
        with pytest.raises(Stop):
            gen.generate([Job("t", "en", out=tmp_path / "a.wav")], progress)
    finally:
        vg.subprocess.Popen = saved
    assert orig and procs and procs[0].poll() is not None
