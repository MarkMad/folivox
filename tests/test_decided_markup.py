"""Decided markup fixes: HTTP errors in Runner.ask are classified; `markup auto` re-reads a sampled preview."""

import email.message
import json
import sys
import urllib.error
from pathlib import Path

import pytest
from typer.testing import CliRunner

from folivox import markup_llm as ml

sys.path.insert(0, str(Path(__file__).parent))
from test_markup_llm import P1, P2, P3, P4, P5, FakeLLM  # noqa: E402


def _http(code, retry_after=None):
    h = email.message.Message()
    if retry_after is not None:
        h["Retry-After"] = retry_after
    return urllib.error.HTTPError("http://x/v1/chat", code, "err", h, None)


class Scripted:
    """Raises the scripted errors in turn, then answers with a valid JSON object."""

    def __init__(self, *errors):
        self.errors, self.calls = list(errors), 0

    def complete_json(self, prompt, system=None, temperature=0.2):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return '{"ok": 1}'


def _runner(llm, tmp_path, **kw):
    sleeps = []
    r = ml.Runner(llm, "m", ml.Cache(None), sleep=sleeps.append, **kw)
    r._wait = lambda s: sleeps.append(s)  # record the whole waits
    return r, sleeps


def test_busy_server_is_waited_out_honouring_retry_after(tmp_path):
    llm = Scripted(_http(429, "7"), _http(503), ConnectionResetError("reset"))
    r, sleeps = _runner(llm, tmp_path)
    assert r.ask("s", "p", lambda d: d) == {"ok": 1}
    assert llm.calls == 4 and sleeps[0] == 7 and len(sleeps) == 3


def test_retry_after_is_capped_and_attempts_are_limited(tmp_path):
    llm = Scripted(*[_http(500, "999")] * 10)
    r, sleeps = _runner(llm, tmp_path)
    with pytest.raises(ml.LLMError):
        r.ask("s", "p", lambda d: d)
    assert llm.calls == ml.Runner.BUSY_TRIES and max(sleeps) == ml.Runner.BUSY_WAIT_CAP


@pytest.mark.parametrize("code", [401, 403, 404])
def test_wrong_key_model_or_url_fails_at_once(tmp_path, code):
    llm = Scripted(_http(code))
    r, sleeps = _runner(llm, tmp_path)
    with pytest.raises(ml.LLMError, match=str(code)):
        r.ask("s", "p", lambda d: d)
    assert llm.calls == 1 and not sleeps


@pytest.mark.parametrize("code", [400, 413, 422])
def test_refused_request_is_a_bad_reply(tmp_path, code):
    r, _ = _runner(Scripted(_http(code)), tmp_path)
    assert r.ask("s", "p", lambda d: d) == {"ok": 1}  # the second try succeeds
    r, _ = _runner(Scripted(_http(code), _http(code)), tmp_path)
    with pytest.raises(ValueError):
        r.ask("s", "p2", lambda d: d)


def test_waiting_sleeps_in_short_steps(tmp_path):
    slept = []
    r = ml.Runner(Scripted(), "m", ml.Cache(None), sleep=slept.append)
    r._wait(2.5)
    assert slept == [1.0, 1.0, 0.5]


def test_cancel_stops_the_waiting(tmp_path):
    llm = Scripted(*[_http(429)] * 10)
    r = ml.Runner(llm, "m", ml.Cache(None), cancelled=lambda: True, sleep=lambda s: None)
    with pytest.raises(ml.LLMError):
        r.ask("s", "p", lambda d: d)
    assert llm.calls == 1


def test_auto_reads_the_whole_book_after_a_preview(tmp_path, monkeypatch):
    from folivox import cli_markup
    from folivox.cli import app

    book = tmp_path / "b.txt"
    book.write_text("Глава 1\n\n" + "\n\n".join((P1, P2, P3, P4)) + "\n\nГлава 2\n\n" + P5 + "\n", encoding="utf-8")
    monkeypatch.setattr(cli_markup, "_llm", lambda provider, model: (FakeLLM(), "fake-model"))
    ml.Bible(sampled=True, total_windows=1, done_windows=1).save(ml.bible_path(book))
    calls = []
    real = ml.analyse
    monkeypatch.setattr(ml, "analyse", lambda *a, **k: calls.append(1) or real(*a, **k))
    res = CliRunner().invoke(app, ["markup", "auto", str(book)])
    assert res.exit_code == 0, res.output
    assert calls
    saved = json.loads(ml.bible_path(book).read_text(encoding="utf-8"))
    assert saved["sampled"] is False and saved["done_windows"] == saved["total_windows"] > 0
