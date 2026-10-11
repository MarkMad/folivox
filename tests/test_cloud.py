"""Cloud voice generators with a fake transport: no network, no keys."""
import base64
import json
import urllib.parse
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from folivox.voicegen import GENERATORS, Job
from folivox.voicegen.cloud import CloudError, Response, cloud_providers, pcm_to_wav
from folivox.voicegen.cloud_apis import Cartesia, ElevenLabs, Gemini, OpenAIVoice

KEY = "sk-test-SECRET-1234"


def wav_bytes(seconds=0.2, sr=24000) -> bytes:
    import io

    buf = io.BytesIO()
    sf.write(buf, (0.1 * np.sin(np.arange(int(sr * seconds)) / 20)).astype("float32"), sr, format="WAV")
    return buf.getvalue()


class Fake:
    """Records requests, replays queued responses (the last one repeats)."""

    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append({"method": method, "url": url, "headers": headers,
                           "json": json.loads(body) if body else None})
        r = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(r, Exception):
            raise r
        return r


def ok(body=b"", status=200, **headers):
    return Response(status, body if isinstance(body, bytes) else json.dumps(body).encode(), headers)


def make(cls, fake, **kw):
    kw.setdefault("model", cls.models[0]["id"])  # pinned: "auto" would first ask the provider which models exist
    return cls(api_key=KEY, transport=fake, sleep=lambda s: None, **kw)


def job(tmp_path, **kw):
    return Job(**{"text": "A calm morning.", "lang": "en", "out": tmp_path / "t.wav", **kw})


def test_registry_and_capabilities():
    found = cloud_providers()
    assert set(found) == {"openai", "gemini", "elevenlabs", "cartesia"}
    assert found["elevenlabs"].modes == ("preset", "design")
    for name, cls in found.items():
        caps = cls.capabilities()
        assert caps["key_env"].endswith("_API_KEY") and caps["languages"] and caps["terms_url"].startswith("https://")
        assert caps["commercial"] is True and not GENERATORS.get(name).local
        assert GENERATORS.get(name).needs == cls.key_env
    assert found["gemini"].modes == ("preset", "design") and found["openai"].modes == ("preset",)
    assert found["cartesia"].modes == ("preset", "localize", "clone")
    assert all(found[n].models and found[n].models[0]["id"] for n in found)


def test_missing_key_message(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr("folivox.config.keychain_get", lambda n: None)
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        GENERATORS.create("gemini")


def test_gemini_request_and_wav(tmp_path):
    pcm = (np.zeros(2400, dtype="<i2")).tobytes()
    fake = Fake(ok({"candidates": [{"content": {"parts": [{"inlineData": {
        "mimeType": "audio/L16;rate=24000", "data": base64.b64encode(pcm).decode()}}]}}]}))
    g = make(Gemini, fake)
    g.generate([job(tmp_path, speaker="Kore", description="calm and warm")])
    c = fake.calls[0]
    assert c["url"].endswith("/models/gemini-3.8-flash-tts:generateContent")
    assert c["headers"]["x-goog-api-key"] == KEY
    part = c["json"]["contents"][0]["parts"][0]
    assert part["text"] == "A calm morning." and part["speech_metadata"] == {"style": "calm and warm"}
    assert c["json"]["generationConfig"]["speechConfig"]["voiceConfig"] == {"voice": "Kore"}
    data, sr = sf.read(str(tmp_path / "t.wav"))
    assert sr == 24000 and len(data) == 2400


def test_gemini_older_model_shape(tmp_path):
    fake = Fake(ok({"candidates": [{"content": {"parts": [{"inlineData": {
        "data": base64.b64encode(wav_bytes()).decode()}}]}}]}))
    g = make(Gemini, fake, model="gemini-2.5-flash-preview-tts")
    g.generate([job(tmp_path, speaker="Puck", description="soft")])
    body = fake.calls[0]["json"]
    assert body["generationConfig"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"] == {"voiceName": "Puck"}
    assert body["contents"][0]["parts"][0]["text"].startswith("Say in this style (soft)")


def test_gemini_blocked_and_unknown_voice(tmp_path):
    g = make(Gemini, Fake(ok({"candidates": [{"finishReason": "SAFETY"}]})))
    with pytest.raises(CloudError, match="no audio"):
        g.generate([job(tmp_path, speaker="Kore")])
    with pytest.raises(CloudError, match="no voice"):
        g.generate([job(tmp_path, speaker="Nobody")])


def test_openai_request(tmp_path):
    fake = Fake(ok(wav_bytes()))
    make(OpenAIVoice, fake).generate([job(tmp_path, speaker="marin", description="slow, warm")])
    c = fake.calls[0]
    assert c["url"] == "https://api.openai.com/v1/audio/speech"
    assert c["headers"]["Authorization"] == f"Bearer {KEY}"
    assert c["json"] == {"model": "gpt-4o-mini-tts", "input": "A calm morning.", "voice": "marin",
                         "response_format": "wav", "instructions": "slow, warm"}
    assert (tmp_path / "t.wav").read_bytes()[:4] == b"RIFF"


def test_openai_tts1_has_no_instructions_and_fewer_voices(tmp_path):
    fake = Fake(ok(wav_bytes()))
    g = make(OpenAIVoice, fake, model="tts-1")
    g.generate([job(tmp_path, speaker="coral", description="ignored")])
    assert "instructions" not in fake.calls[0]["json"]
    with pytest.raises(CloudError, match="no voice"):
        g.generate([job(tmp_path, speaker="marin")])


def test_text_limit(tmp_path):
    with pytest.raises(CloudError, match="limit"):
        make(OpenAIVoice, Fake(ok(b""))).generate([job(tmp_path, text="x" * 5000)])


def test_elevenlabs_preset(tmp_path):
    pcm = np.zeros(4800, dtype="<i2").tobytes()
    fake = Fake(ok(pcm))
    make(ElevenLabs, fake).generate([job(tmp_path, speaker="abc123", seed=7)])
    c = fake.calls[0]
    assert c["url"] == "https://api.elevenlabs.io/v1/text-to-speech/abc123?output_format=pcm_24000"
    assert c["headers"]["xi-api-key"] == KEY
    assert c["json"] == {"text": "A calm morning.", "model_id": "eleven_v4", "seed": 7}
    assert sf.read(str(tmp_path / "t.wav"))[1] == 24000


def test_elevenlabs_voice_list(tmp_path):
    fake = Fake(ok({"voices": [{"voice_id": "v1", "name": "Rachel", "labels": {"gender": "female"}}],
                    "has_more": False}))
    g = make(ElevenLabs, fake)
    assert g.speakers() == {"v1": ("", "f")} and g.names == {"v1": "Rachel"}
    q = urllib.parse.urlparse(fake.calls[0]["url"])
    assert q.path == "/v2/voices" and "category=premade" in q.query
    g.speakers()
    assert len(fake.calls) == 1  # cached


def test_elevenlabs_design_one_request_per_three_takes(tmp_path):
    text = "A quiet morning on the river. " * 5
    previews = [{"audio_base_64": base64.b64encode(np.zeros(2400, dtype="<i2").tobytes()).decode(),
                 "media_type": "audio/pcm", "generated_voice_id": f"g{i}"} for i in range(3)]
    fake = Fake(ok({"previews": previews, "text": text}))
    g = make(ElevenLabs, fake)
    g.mode = "design"
    desc = "A calm middle-aged British woman, warm and unhurried"
    jobs = [Job(text, "en", description=desc, out=tmp_path / f"{i}.wav") for i in range(3)]
    done = []
    g.generate(jobs, lambda j, s: done.append(j))
    assert len(fake.calls) == 1 and len(done) == 3
    assert fake.calls[0]["url"].startswith("https://api.elevenlabs.io/v1/text-to-voice/design")
    assert fake.calls[0]["json"]["voice_description"].startswith("A calm") and fake.calls[0]["json"]["text"] == text
    assert all(j.out.exists() for j in jobs)
    assert ElevenLabs.estimate_for(len(text), 3, "design")["chars"] == len(text)
    assert ElevenLabs.estimate_for(len(text), 4, "design")["chars"] == 2 * len(text)


def test_elevenlabs_design_input_rules(tmp_path):
    g = make(ElevenLabs, Fake(ok({})))
    g.mode = "design"
    with pytest.raises(CloudError, match="100–1000"):
        g.generate([Job("short", "en", description="x" * 30, out=tmp_path / "a.wav")])
    with pytest.raises(CloudError, match="20 characters"):
        g.generate([Job("x" * 150, "en", description="short", out=tmp_path / "a.wav")])


def test_cartesia_request_and_voices(tmp_path):
    fake = Fake(ok(wav_bytes()))
    make(Cartesia, fake).generate([job(tmp_path, speaker="uuid-1")])
    c = fake.calls[0]
    assert c["url"] == "https://api.cartesia.ai/tts/bytes"
    assert c["headers"]["Authorization"] == f"Bearer {KEY}" and c["headers"]["Cartesia-Version"] == "2026-08-14"
    assert c["json"]["voice"] == {"id": "uuid-1"} and c["json"]["model_id"] == "sonic-3.6"
    assert c["json"]["output_format"] == {"container": "wav", "encoding": "pcm_s16le", "sample_rate": 24000}
    fake = Fake(ok({"data": [{"id": "u1", "name": "Ann", "gender": "feminine", "language": "en"}], "has_more": False}))
    assert make(Cartesia, fake).speakers("en") == {"u1": ("en", "f")}
    assert "language=en" in fake.calls[0]["url"]


@pytest.mark.parametrize("status,body,kind,words", [
    (401, {"error": {"message": "bad key"}}, "auth", "rejected the API key"),
    (403, {"detail": {"status": "invalid_api_key", "message": "no"}}, "auth", "rejected"),
    (402, {"detail": "pay"}, "quota", "quota or credits"),
    (429, {"error": {"type": "insufficient_quota", "code": "credit_balance_exhausted", "message": "m"}}, "quota",
     "exhausted"),
    (429, {"detail": {"status": "quota_exceeded", "message": "You have 0 credits left"}}, "quota", "0 credits"),
    (429, {"error": {"type": "rate_limit_error", "message": "slow"}}, "rate_limit", "rate limit"),
    (422, {"detail": [{"msg": "bad field", "loc": ["body"]}]}, "bad_request", "refused"),
    (503, {"error": {"message": "down"}}, "server", "server error"),
])
def test_error_mapping(tmp_path, status, body, kind, words):
    fake = Fake(ok(body, status=status, **{"retry-after": "7"}))
    with pytest.raises(CloudError) as e:
        make(OpenAIVoice, fake).generate([job(tmp_path, speaker="coral")])
    assert e.value.kind == kind and words in str(e.value)
    assert KEY not in str(e.value) and "SECRET" not in str(e.value)
    assert len(fake.calls) == (3 if kind in ("rate_limit", "server") else 1)  # transient errors are retried


def test_retry_then_success_and_network_error(tmp_path):
    fake = Fake(ok({"error": {"message": "slow"}}, status=429), ok(wav_bytes()))
    make(OpenAIVoice, fake).generate([job(tmp_path, speaker="coral")])
    assert len(fake.calls) == 2
    net = Fake(CloudError("Cannot reach the provider: down", "network"))
    with pytest.raises(CloudError, match="Cannot reach"):
        make(OpenAIVoice, net).generate([job(tmp_path, speaker="coral")])
    assert len(net.calls) == 3


def test_pcm_helper():
    assert pcm_to_wav(b"\0\0" * 10)[:4] == b"RIFF"
    assert isinstance(Path, type)


def test_auto_model_picks_the_newest_the_provider_lists(tmp_path):
    gem = Fake(ok({"models": [{"name": f"models/{n}", "supportedGenerationMethods": ["generateContent"]} for n in (
        "gemini-2.5-pro-preview-tts", "gemini-3.1-flash-tts-preview", "gemini-3.8-flash-lite-tts",
        "gemini-3.9-flash-tts", "gemini-3.8-flash-tts", "gemini-2.5-flash-native-audio-latest")]}))
    assert Gemini(api_key=KEY, transport=gem).model == "gemini-3.9-flash-tts"
    ids = ("tts-1", "gpt-4o-mini-tts", "gpt-4o-mini-tts-2025-12-15", "gpt-audio")
    oa = Fake(ok({"data": [{"id": i} for i in ids]}))
    assert OpenAIVoice(api_key=KEY, transport=oa).model == "gpt-4o-mini-tts"
    el = Fake(ok({"data": []}))  # unexpected shape: falls back to the declared best
    assert ElevenLabs(api_key=KEY, transport=el).model == "eleven_v4"
    el = Fake(ok([{"model_id": i, "can_do_text_to_speech": True} for i in
                  ("eleven_v3", "eleven_v5", "eleven_v4_turbo", "eleven_flash_v2_5")]))
    assert ElevenLabs(api_key=KEY, transport=el).model == "eleven_v5"
    assert Cartesia(api_key=KEY, transport=Fake(ok({}))).model == "sonic-3.6"
    assert Gemini(api_key=KEY, transport=Fake(ok({}, status=503)), sleep=lambda s: None).model == "gemini-3.8-flash-tts"


def test_pinned_model_is_used_without_discovery_and_bad_key_surfaces(tmp_path):
    fake = Fake(ok(wav_bytes()))
    g = make(OpenAIVoice, fake, model="tts-1-hd")
    g.generate([job(tmp_path, speaker="coral")])
    assert [c["url"].rsplit("/", 1)[-1] for c in fake.calls] == ["speech"]
    assert fake.calls[0]["json"]["model"] == "tts-1-hd"
    with pytest.raises(CloudError, match="rejected the API key"):
        Gemini(api_key=KEY, transport=Fake(ok({"error": {}}, status=401))).model  # noqa: B018


def test_elevenlabs_v4_style_becomes_an_audio_tag_other_models_ignore_it(tmp_path):
    fake = Fake(ok(np.zeros(2400, dtype="<i2").tobytes()))
    make(ElevenLabs, fake).generate([job(tmp_path, speaker="v", description="calm, slow narration")])
    assert fake.calls[0]["json"]["text"] == "[calm, slow narration] A calm morning."
    make(ElevenLabs, fake, model="eleven_multilingual_v2").generate([job(tmp_path, speaker="v", description="calm")])
    assert fake.calls[1]["json"]["text"] == "A calm morning."


def test_gemini_design_creates_uses_and_deletes_the_voice(tmp_path):
    audio = {"candidates": [{"content": {"parts": [{"inlineData": {"data": base64.b64encode(wav_bytes()).decode()}}]}}]}
    fake = Fake(ok({"id": "voice_abc"}), ok(audio), ok(audio), ok(b""))
    g = make(Gemini, fake)
    g.mode = "design"
    jobs = [job(tmp_path, description="A calm middle-aged woman, warm low voice", lang="ru", out=tmp_path / f"{i}.wav")
            for i in range(2)]
    g.generate(jobs)
    create, s1, s2, delete = fake.calls
    assert create["method"] == "POST" and create["url"].endswith("/v1beta/voices")
    v = create["json"]["voice"]
    assert create["json"]["store"] is True and v["type"] == "prompted" and v["language_code"] == "ru-RU"
    assert v["prompted"]["input"].startswith("A calm middle-aged") and v["model"] == "gemini-3.8-flash-tts"
    assert s1["json"]["generationConfig"]["speechConfig"]["voiceConfig"] == {"voice": "voice_abc"}
    assert "speech_metadata" not in s1["json"]["contents"][0]["parts"][0]
    assert delete["method"] == "DELETE" and delete["url"].endswith("/v1beta/voices/voice_abc")  # one voice, removed
    g2 = make(Gemini, Fake(ok({})), model="gemini-2.5-flash-preview-tts")
    g2.mode = "design"
    with pytest.raises(CloudError, match="gemini-3.8"):
        g2.generate([job(tmp_path, description="x" * 30)])


def test_gemini_design_deletes_the_voice_even_when_synthesis_fails(tmp_path):
    fake = Fake(ok({"id": "voice_abc"}), ok({"error": {"message": "bad"}}, status=400), ok(b""))
    g = make(Gemini, fake)
    g.mode = "design"
    with pytest.raises(CloudError):
        g.generate([job(tmp_path, description="A calm middle-aged woman")])
    assert fake.calls[-1]["method"] == "DELETE"


def test_cartesia_localize_and_cleanup(tmp_path):
    accents = {"accents": [{"id": "russian", "language": "ru", "is_locale_default": True},
                           {"id": "other-ru", "language": "ru", "is_locale_default": False}]}
    fake = Fake(ok(accents), ok({"id": "new-voice"}), ok(wav_bytes()), ok(b"", status=204))
    g = make(Cartesia, fake)
    g.mode = "localize"
    g.generate([job(tmp_path, lang="ru", speaker="base-voice")])
    acc, loc, tts, delete = fake.calls
    assert "accents" in acc["url"] and loc["url"].endswith("/voices/localize")
    assert loc["json"]["voice_id"] == "base-voice" and loc["json"]["accent"] == "russian"
    assert tts["json"]["voice"] == {"id": "new-voice"} and tts["json"]["language"] == "ru"
    assert delete["method"] == "DELETE" and delete["url"].endswith("/voices/new-voice")
    g = make(Cartesia, Fake(ok({"accents": []})))
    g.mode = "localize"
    with pytest.raises(CloudError, match="cannot localize"):
        g.generate([job(tmp_path, lang="ru", speaker="b")])


def test_cartesia_clone_uploads_the_sample_and_deletes_the_clone(tmp_path):
    clip = tmp_path / "me.flac"
    sf.write(str(clip), (0.1 * np.sin(np.arange(24000) / 20)).astype("float32"), 24000)
    seen = []

    def transport(method, url, headers, body, timeout):
        seen.append((method, url, headers, body))
        if url.endswith("/voices/clone"):
            return ok({"id": "clone-1"})
        return ok(wav_bytes()) if url.endswith("/tts/bytes") else ok(b"", status=204)

    g = make(Cartesia, transport)
    g.mode = "clone"
    g.generate([job(tmp_path, speaker="", lang="en", reference=clip)])
    m, url, headers, body = seen[0]
    assert url.endswith("/voices/clone") and headers["Content-Type"].startswith("multipart/form-data; boundary=")
    assert b'name="clip"' in body and b"RIFF" in body and b'name="language"' in body  # FLAC sent as WAV
    assert seen[-1][0] == "DELETE" and seen[-1][1].endswith("/voices/clone-1")
    with pytest.raises(CloudError, match="own voices"):
        g.generate([job(tmp_path, reference=None)])


def test_estimates_follow_the_model():
    assert OpenAIVoice.estimate_for(1000, 1, "preset", "tts-1-hd")["usd"] == pytest.approx(0.03)
    assert OpenAIVoice.estimate_for(1000, 1, "preset", "tts-1")["usd"] == pytest.approx(0.015)
    assert ElevenLabs.estimate_for(1000, 1, "preset", "eleven_flash_v2_5")["usd"] == pytest.approx(0.04)
    assert Cartesia.estimate_for(100, 1, "localize")["chars"] == 325


def test_voice_details_for_the_picker():
    gem = Fake(ok({"voices": [{"display_name": "Kore", "gender": "female", "persona": "Storyteller & Narrator",
                               "pitch": "high", "description": "Soft and calm."},
                              {"display_name": "Library Voice 1", "gender": "male"}]}))
    g = make(Gemini, gem)
    assert g.speakers()["Kore"] == ("", "f") and "Library Voice 1" not in g.speakers()  # only the 30 documented names
    assert g.details["Kore"] == {"traits": "Storyteller & Narrator · high pitch", "description": "Soft and calm."}
    assert "language_code=en-US" in gem.calls[0]["url"]
    down = make(Gemini, Fake(ok({"error": {"message": "x"}}, status=503)))
    assert len(down.speakers()) == 30 and down.details == {}  # falls back to the declared names
    el = Fake(ok({"voices": [{"voice_id": "v1", "name": "Sarah", "labels": {"gender": "female", "age": "middle_aged",
                                                                           "accent": "american"},
                              "description": "Warm.", "preview_url": "https://cdn.example/s.mp3"}], "has_more": False}))
    e = make(ElevenLabs, el)
    e.speakers()
    assert e.details["v1"] == {"traits": "middle aged · american", "description": "Warm.",
                               "preview_url": "https://cdn.example/s.mp3"}
    ca = make(Cartesia, Fake(ok({"data": [{"id": "u", "name": "Ann", "gender": "feminine", "tagline": "Calm",
                                           "description": "Friendly.", "preview_file_url": None}], "has_more": False})))
    ca.speakers("ru")
    assert ca.details["u"] == {"traits": "Calm", "description": "Friendly.", "preview_url": ""}
    oa = make(OpenAIVoice, Fake(ok({})))
    assert oa.speakers()["onyx"] == ("", "m") and "openai.fm" in oa.voices_note and oa.details["onyx"]["traits"]
