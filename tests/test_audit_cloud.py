"""Audit regressions for the cloud TTS / voice generator plumbing."""

import json
import threading

import pytest

from folivox.tts import saved
from folivox.tts.cloud import CloudTTS, CloudVoice, CostCapReached
from folivox.voicegen.cloud import CloudError, CloudGenerator, Response
from folivox.voicegen.cloud_apis import Cartesia, ElevenLabs, OpenAIVoice


def gen(cls, replies, **kw):
    calls = []

    def transport(method, url, headers, body, timeout):
        calls.append((method, url, body))
        return replies.pop(0) if replies else Response(200, b"RIFF" + b"\0" * 200, {})

    g = cls(api_key="k", transport=transport, sleep=lambda s: None, **kw)
    g.calls = calls
    return g


@pytest.mark.parametrize("value", ["-5", "nan", "inf", "1e12"])
def test_bad_retry_after_does_not_crash(value):
    g = gen(OpenAIVoice, [Response(429, b"{}", {"retry-after": value})], model="tts-1")
    assert g.call("GET", "https://x").status == 200


def test_empty_audio_is_rejected():
    g = gen(OpenAIVoice, [Response(200, b"", {})], model="tts-1")
    from folivox.voicegen import Job
    with pytest.raises(CloudError) as e:
        g.synth(Job(text="hi", lang="en", speaker="alloy"))
    assert e.value.kind == "bad_request"


def test_cartesia_does_not_pollute_shared_names():
    g = gen(Cartesia, [Response(200, json.dumps({"data": [{"id": "v1", "name": "Ann"}]}).encode(), {})])
    g.speakers("en")
    assert "v1" not in CloudGenerator.names and g.names == {"v1": "Ann"}


def test_elevenlabs_style_tag_is_counted():
    g = gen(ElevenLabs, [], model="eleven_v3")
    e = CloudTTS("elevenlabs", generator=g)
    e.prepare("hello", CloudVoice("elevenlabs", "eleven_v3", "v", "calm"))
    assert e.chars_sent == len("[calm] hello")


def test_elevenlabs_unknown_model_priced_conservatively():
    assert ElevenLabs.estimate_for(1000, model="eleven_v9")["usd"] == 0.08


def test_budget_cap_is_atomic_across_threads():
    g = gen(OpenAIVoice, [], model="tts-1")
    e = CloudTTS("openai", generator=g, max_cost=15 * 3000 / 1e6)  # room for three 1000-char fragments
    ok, capped = [], []

    def run():
        try:
            e.prepare("a" * 1000, CloudVoice("openai", "tts-1", "alloy"))
            ok.append(1)
        except CostCapReached:
            capped.append(1)

    ts = [threading.Thread(target=run) for _ in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(ok) == 3 and e.chars_sent == 3000


def test_saved_skips_malformed(tmp_path, monkeypatch):
    p = tmp_path / "cloud_voices.json"
    p.write_text(json.dumps([{"provider": "x"}, "junk", {"provider": "x", "id": "a", "name": "A"}]))
    monkeypatch.setattr(saved, "_path", lambda: p)
    assert saved.find("x", "a")["name"] == "A"
    assert saved.rename("x", "a", "B")


def test_server_error_is_resent_twice_with_growing_pauses(tmp_path):
    from folivox.voicegen.cloud import CloudError
    from folivox.voicegen.cloud_apis import OpenAIVoice

    sleeps: list[float] = []

    class Down:
        n = 0

        def __call__(self, method, url, headers, body, timeout):
            from folivox.voicegen.cloud import Response
            Down.n += 1
            return Response(503, b"{}", {})

    gen = OpenAIVoice(api_key="sk-test", transport=Down(), sleep=sleeps.append)
    try:
        gen.call("POST", "https://example.invalid/x", {"a": 1})
    except CloudError as e:
        assert e.kind == "server"
    assert Down.n == 3 and len(sleeps) == 2 and sleeps[0] < sleeps[1]
