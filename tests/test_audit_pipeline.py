"""Audit regressions: silent takes survive a resume, cached sample rate follows the takes on disk."""

from __future__ import annotations

import numpy as np

from folivox.audio import save
from folivox.journal import Journal
from folivox.pipeline import _cached_sample_rate
from folivox.text.chunk import Chunk


def _chunk(text: str) -> Chunk:
    c = Chunk.__new__(Chunk)
    c.__dict__.update(index=0, text=text, source=text, pause_after=0.3, kind="p", speaker=0, markup="", lang="")
    return c


class _SilentEngine:
    sample_rate = 24000
    local = True
    parallel = 1
    max_chars = 300

    def prepare(self, text, voice, seed=0, **kw):
        return None, 0.0

    def finish(self, prepared, voice, speed=1.0):
        return np.zeros(0, np.float32), 0.0


def test_silent_take_counts_as_done(tmp_path):
    from folivox.pipeline import Events, RenderOptions, synthesize_pending

    j = Journal(tmp_path)
    j.set_plan([("Ch", [_chunk("Hello there.")])], "v", "s")
    opts = RenderOptions.__new__(RenderOptions)
    opts.__dict__.update(qa_threshold=0.2, max_takes=1, lang="en", speed=1.0)
    synthesize_pending(j, _SilentEngine(), object(), None, opts, Events())
    (c,) = j.chunks()
    assert j.is_done(c.key) and not j.pending()
    assert j.audit() == []  # a resume does not synthesise (and bill) it again
    j.close()


def test_cached_sample_rate_reads_takes(tmp_path):
    j = Journal(tmp_path)
    j.set_plan([("Ch", [_chunk("Hello there.")])], "v", "s")
    assert _cached_sample_rate(j) is None
    (c,) = j.chunks()
    save(j.audio_path(c.key), np.zeros(4410, np.float32), 44100)
    assert _cached_sample_rate(j) == 44100
    j.close()


def test_cli_user_errors_exit_cleanly(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from folivox import diag
    from folivox.cli import app

    def boom(*a, **k):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(diag, "support_bundle", boom)
    r = CliRunner().invoke(app, ["doctor", "--bundle", str(tmp_path)])
    assert r.exit_code == 1 and "Could not write the support bundle" in r.output
    r = CliRunner().invoke(app, ["voices", "remove", "no-such-voice-xyz"])
    assert r.exit_code == 2 and isinstance(r.exception, SystemExit)
