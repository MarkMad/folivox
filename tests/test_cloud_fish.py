"""Fish Audio (Drama 3) cloud engine with a fake transport: no network, no keys."""
import base64
import json

import numpy as np
import pytest
import soundfile as sf
from test_cloud import KEY, Fake, job, make, ok, wav_bytes

from folivox.tts.cloud import CloudTTS
from folivox.tts.cost import estimate
from folivox.voicegen.cloud import CloudError
from folivox.voicegen.cloud_apis import FishAudio


def pcm(n=2400) -> bytes:
    return (3000 * np.sin(np.arange(n) / 20)).astype("<i2").tobytes()


def test_tts_request_for_drama3(tmp_path):
    fake = Fake(ok(pcm()))
    out = make(FishAudio, fake).generate([job(tmp_path, speaker="vid", lang="ru", description="calm, warm")])
    c = fake.calls[0]
    assert c["url"] == "https://api.fish.audio/v1/tts"
    assert c["headers"]["Authorization"] == f"Bearer {KEY}" and c["headers"]["model"] == "drama-3"
    assert c["json"]["reference_id"] == "vid" and c["json"]["text"] == "[calm, warm] A calm morning."
    assert c["json"]["format"] == "pcm" and c["json"]["sample_rate"] == 24000 and c["json"]["language"] == "ru"
    assert c["json"]["normalize"] is False
    audio, sr = sf.read(out[0])
    assert sr == 24000 and len(audio) == 2400


def test_no_direction_when_no_style_and_voice_required(tmp_path):
    fake = Fake(ok(pcm()))
    make(FishAudio, fake).generate([job(tmp_path, speaker="vid")])
    assert fake.calls[0]["json"]["text"] == "A calm morning."
    with pytest.raises(CloudError, match="pick a voice"):
        make(FishAudio, Fake(ok(pcm()))).generate([job(tmp_path)])


def test_empty_audio_is_an_error(tmp_path):
    with pytest.raises(CloudError, match="no audio"):
        make(FishAudio, Fake(ok(b""))).generate([job(tmp_path, speaker="v")])


def test_insufficient_credit_is_a_quota_error(tmp_path):
    body = {"status": 402, "message": "Insufficient API credit. API credit is managed independently."}
    with pytest.raises(CloudError, match="Insufficient API credit") as e:
        make(FishAudio, Fake(ok(body, status=402))).generate([job(tmp_path, speaker="v")])
    assert e.value.kind == "quota"


def test_voice_library_listing():
    page = {"items": [
        {"_id": "z9", "type": "tts", "state": "trained", "title": "Community", "tags": ["male"], "languages": ["ru"],
         "author": {"nickname": "someone"}},
        {"_id": "a1", "type": "tts", "state": "trained", "title": "Anna", "tags": ["female", "calm", "Russian"],
         "languages": ["ru"], "description": "soft", "samples": [{"audio": "https://x/a.mp3"}],
         "author": {"nickname": "Fish Official"}},
        {"_id": "b2", "type": "tts", "state": "created", "title": "Untrained", "tags": []},
        {"_id": "c3", "type": "svc", "state": "trained", "title": "Converter", "tags": []}]}
    fake = Fake(ok({"items": []}), ok(page))
    g = make(FishAudio, fake)
    assert list(g.speakers("ru").items()) == [("a1", ("ru", "f")), ("z9", ("ru", "m"))]  # Fish's own voices first
    assert "self=true" in fake.calls[0]["url"]
    assert "licensed=true" in fake.calls[1]["url"] and "language=ru" in fake.calls[1]["url"]
    assert g.details["a1"]["traits"].startswith("Fish Official")
    assert g.names["a1"] == "Anna" and g.details["a1"]["preview_url"] == "https://x/a.mp3"
    assert "female" not in g.details["a1"]["traits"]


def test_featured_english_voices_come_first():
    g = make(FishAudio, Fake(ok({"items": []})))
    assert list(g.speakers("en"))[0] == "bf322df2096a46f18c579d0baa36f41d"
    assert g.names["c70cfb98867a4bfb9ae20d2401257b92"] == "Delia"


def test_design_makes_a_voice_uses_it_and_deletes_it(tmp_path):
    seen = []
    cand = {"candidates": [{"audio_base64": base64.b64encode(wav_bytes()).decode(), "text": "Sample line."}]}

    def transport(method, url, headers, body, timeout):
        seen.append((method, url, headers, body))
        if url.endswith("/v1/voice-design"):
            return ok(cand)
        if url.endswith("/model") and method == "POST":
            return ok({"_id": "new-voice", "state": "trained"}, status=201)
        return ok(pcm()) if url.endswith("/v1/tts") else ok(b"")

    g = make(FishAudio, transport)
    g.mode = "design"
    g.generate([job(tmp_path, lang="en", description="Calm middle-aged narrator, warm low voice")])
    design, create, tts, delete = seen
    assert design[2]["model"] == "voice-design-1"
    assert json.loads(design[3]) == {"instruction": "Calm middle-aged narrator, warm low voice", "n": 1,
                                     "language": "en"}
    assert create[2]["Content-Type"].startswith("multipart/form-data; boundary=")
    for part in (b'name="voices"', b'name="texts"', b"Sample line.", b"train_mode", b'name="visibility"\r\n\r\nprivate',
                 b'name="enhance_audio_quality"\r\n\r\nfalse', b"RIFF"):
        assert part in create[3]
    assert json.loads(tts[3])["reference_id"] == "new-voice"
    assert delete[0] == "DELETE" and delete[1].endswith("/model/new-voice")


def test_design_needs_a_description_and_a_candidate(tmp_path):
    g = make(FishAudio, Fake(ok({})))
    g.mode = "design"
    with pytest.raises(CloudError, match="description"):
        g.generate([job(tmp_path, description="short")])
    with pytest.raises(CloudError, match="no voice candidate"):
        g.generate([job(tmp_path, description="a long enough description")])


def test_clone_uploads_the_sample_as_wav_and_deletes_the_clone(tmp_path):
    clip = tmp_path / "me.flac"
    sf.write(str(clip), (0.1 * np.sin(np.arange(24000) / 20)).astype("float32"), 24000)
    seen = []

    def transport(method, url, headers, body, timeout):
        seen.append((method, url, body))
        if url.endswith("/model") and method == "POST":
            return ok({"_id": "clone-1", "state": "trained"}, status=201)
        return ok(pcm()) if url.endswith("/v1/tts") else ok(b"")

    g = make(FishAudio, transport)
    g.mode = "clone"
    g.generate([job(tmp_path, lang="en", reference=clip)])
    assert b'name="voices"' in seen[0][2] and b"RIFF" in seen[0][2] and b'name="texts"' not in seen[0][2]
    assert b'name="enhance_audio_quality"\r\n\r\ntrue' in seen[0][2]
    assert seen[-1][0] == "DELETE" and seen[-1][1].endswith("/model/clone-1")
    with pytest.raises(CloudError, match="own voices"):
        g.generate([job(tmp_path, reference=None)])


def test_failed_training_is_reported(tmp_path):
    clip = tmp_path / "me.wav"
    clip.write_bytes(wav_bytes())
    g = make(FishAudio, lambda *a: ok({"_id": "x", "state": "failed"}, status=201))
    g.mode = "clone"
    with pytest.raises(CloudError, match="could not train"):
        g.generate([job(tmp_path, reference=clip)])


def test_price_is_per_utf8_byte_so_language_matters():
    en = estimate("fish", 100_000, "drama-3", takes=1, qa=False, lang="en")
    ru = estimate("fish", 100_000, "drama-3", takes=1, qa=False, lang="ru")
    assert en["usd"] == pytest.approx(5.0) and ru["usd"] == pytest.approx(9.25)
    assert estimate("fish", 100_000, "s2.1-pro", takes=1, qa=False, lang="en")["usd"] == pytest.approx(1.5)
    assert FishAudio.estimate_for(0, 1, "design")["usd"] == pytest.approx(0.01)
    assert estimate("fish", 10, "s2.1-pro-free", lang="en")["usd"] == 0


def test_engine_spend_follows_language(tmp_path):
    eng = CloudTTS("fish", generator=make(FishAudio, Fake(ok(pcm()))))
    voice = eng.make_voice("vid", "calm", "ru")
    assert voice.mode == "preset" and voice.style == "calm"
    eng.chars_sent = 1000
    assert eng.spent_usd == pytest.approx(1000 * 1.85 * 50 / 1e6, abs=1e-3)
    assert eng.voice_modes() == ("preset", "design", "clone")


def test_library_scope_and_capabilities():
    caps = FishAudio.capabilities()
    assert [s["id"] for s in caps["voice_scopes"]] == ["licensed", "all"] and "ru" in caps["voice_langs"]
    fake = Fake(ok({"items": []}), ok({"items": []}))
    g = make(FishAudio, fake)
    g.library = "all"
    g.speakers("de")
    assert "licensed" not in fake.calls[1]["url"] and "language=de" in fake.calls[1]["url"]
    fake = Fake(ok({"items": []}))
    make(FishAudio, fake).speakers("")  # every language: no language filter
    assert "language" not in fake.calls[1]["url"] and "licensed=true" in fake.calls[1]["url"]


# ---- several voices: a markup speaker gets a Fish voice of their own -----------------------------------------

def _two_speaker_book(tmp_path):
    from folivox import markup as mk
    from folivox.readers import read_book

    p = tmp_path / "b.txt"
    p.write_text("The lake was calm this morning, and nobody spoke.\n\n"
                 "I will not go, she said. The road is long.\n", encoding="utf-8")
    book = read_book(p)
    m = mk.Markup()
    m.ensure_speaker(1, "Anna").voice = "fish:anna-id"
    m.ensure_speaker(2, "Boris").voice = "fish-design:a deep calm old man"
    text = book.chapters(2)[0].blocks[1].text
    m.assign(0, 1, 0, len(text), 1, ("whispering",))
    mk.stamp(m, book.chapters(2))
    return book, m


def _engine(fake):
    return CloudTTS("fish", generator=make(FishAudio, fake))


def test_speakers_get_their_own_fish_voices_and_tags_go_in_brackets(tmp_path):
    from folivox.journal import Journal
    from folivox.pipeline import Events, RenderOptions, cloud_speaker_voices, plan, synthesize_pending

    book, m = _two_speaker_book(tmp_path)
    m.speaker(2).voice = "fish-design:a deep calm old man"
    mpath = tmp_path / "b.markup.json"
    m.save(mpath)
    fake = Fake(ok(pcm()))
    eng = _engine(fake)
    opts = RenderOptions(output=tmp_path / "o.m4b", qa=False, lang="en", tts="fish", tts_voice="narr-id",
                         markup=mpath, accept_cloud=True)
    narrator = eng.make_voice("narr-id", None, "en", "preset")
    j = Journal(tmp_path / "w")
    from folivox.pipeline import load_markup

    markup = load_markup(book, opts, Events())
    voices, made = cloud_speaker_voices(markup, eng, opts, j, Events())
    assert voices[1].speaker == "anna-id" and made == []  # a library voice is used as it is, never made or deleted
    assert voices[1].id != narrator.id
    assert eng.make_voice("", None, "en", "preset").id != voices[1].id
    plan(book, opts, j, narrator.id, Events(), eng, markup, voices)
    synthesize_pending(j, eng, narrator, None, opts, Events(), voices)
    sent = [(c["json"]["reference_id"], c["json"]["text"]) for c in fake.calls if c["url"].endswith("/v1/tts")]
    assert {r for r, _ in sent} == {"narr-id", "anna-id"}
    assert any(r == "anna-id" and t.startswith("[whispering] ") for r, t in sent)
    assert all(not t.startswith("[") for r, t in sent if r == "narr-id")


def test_described_speaker_voice_is_made_remembered_and_released(tmp_path):
    from folivox.journal import Journal
    from folivox.pipeline import Events, RenderOptions, _release_speaker_voices, cloud_speaker_voices

    book, m = _two_speaker_book(tmp_path)
    m.ensure_speaker(1).voice = ""
    m.assign(0, 0, 0, 5, 2)
    cand = {"candidates": [{"audio_base64": base64.b64encode(wav_bytes()).decode(), "text": "hi"}]}
    seen = []

    def fake(method, url, headers, body, timeout):
        seen.append((method, url))
        if url.endswith("/v1/voice-design"):
            return ok(cand)
        return ok({"_id": "made-1", "state": "trained"}) if url.endswith("/model") and method == "POST" else ok(b"")

    eng = _engine(fake)
    opts = RenderOptions(output=tmp_path / "o.m4b", lang="en", tts="fish")
    j = Journal(tmp_path / "w")
    voices, made = cloud_speaker_voices(m, eng, opts, j, Events())
    assert voices[2].speaker == "made-1" and voices[2].mode == "design" and len(made) == 1
    n = len(seen)
    again, _ = cloud_speaker_voices(m, _engine(fake), opts, j, Events())  # an interrupted run goes on with it
    assert again[2].speaker == "made-1" and len(seen) == n
    _release_speaker_voices(eng, made, opts, j, Events())
    assert seen[-1][0] == "DELETE" and seen[-1][1].endswith("/model/made-1")
    assert j.meta("cloud_speaker_voices") == {}


def test_other_online_engines_still_refuse_several_speakers(tmp_path):
    from folivox.journal import Journal
    from folivox.pipeline import Events, RenderOptions, cloud_speaker_voices

    _, m = _two_speaker_book(tmp_path)
    m.assign(0, 1, 0, 5, 1)
    opts = RenderOptions(output=tmp_path / "o.m4b", tts="openai")
    with pytest.raises(RuntimeError, match="Several speakers"):
        cloud_speaker_voices(m, None, opts, Journal(tmp_path / "w"), Events())
