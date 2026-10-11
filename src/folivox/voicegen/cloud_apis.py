"""Gemini, OpenAI, ElevenLabs and Cartesia voice generators (endpoints, models and prices checked against the
providers' documentation and live calls in October 2026; see CONTRIBUTING for how to add another).

Models: ``model="auto"`` (the default) asks the provider which models the key can use and takes the newest good
one; a name pins it (``[voicegen.<name>] model = "..."`` in config.toml, ``--model`` on the command line)."""

from __future__ import annotations

import math
import re
import urllib.parse
import uuid
from pathlib import Path

from folivox.voicegen import Job
from folivox.voicegen.cloud import CloudError, CloudGenerator, b64, file_as_wav, pcm_to_wav, to_wav

LANGS = ("en", "ru", "de", "fr", "es", "it", "zh", "ja", "ko")


def _model(id_: str, label: str, note: str = "") -> dict:
    return {"id": id_, "label": label, "note": note}


class Gemini(CloudGenerator):
    """Gemini API speech generation: 30 preset voices, or a voice designed from a description (3.8 models)."""

    name, label, modes, languages = "gemini", "Gemini API", ("preset", "design"), LANGS
    mode_labels = {"preset": "Pick a voice", "design": "Describe a voice (made for this run, then deleted)"}
    style = True
    blurb = (
        "Google's voices: 30 ready-made ones, or describe a new voice in words (it exists only while the "
        "takes are made). Understands a note like 'calm audiobook narrator'. A free tier exists (Google "
        'may then use your text); the paid tier costs a fraction of a cent per sample.'
    )
    key_env = "GEMINI_API_KEY"
    price_note = ("Paid tier about $0.0023 per 10 s of audio on gemini-3.8-flash-tts (doubles in 2027); a free tier "
                  "exists, but Google may then use your text for product improvement.")
    terms_url = "https://ai.google.dev/gemini-api/terms"
    docs_url = "https://ai.google.dev/gemini-api/docs/generate-content/speech-generation"
    max_chars = 4000
    models = (_model("gemini-3.8-flash-tts", "Gemini 3.8 Flash TTS", "newest; also designs voices"),
              _model("gemini-3.8-flash-lite-tts", "Gemini 3.8 Flash-Lite TTS", "cheaper"),
              _model("gemini-3.1-flash-tts-preview", "Gemini 3.1 Flash TTS (preview)"),
              _model("gemini-2.5-pro-preview-tts", "Gemini 2.5 Pro TTS (preview)"),
              _model("gemini-2.5-flash-preview-tts", "Gemini 2.5 Flash TTS (preview)"))
    VOICES = ("Zephyr", "Puck", "Charon", "Kore", "Fenrir", "Leda", "Orus", "Aoede", "Callirrhoe", "Autonoe",
              "Enceladus", "Iapetus", "Umbriel", "Algieba", "Despina", "Erinome", "Algenib", "Rasalgethi",
              "Laomedeia", "Achernar", "Alnilam", "Schedar", "Gacrux", "Pulcherrima", "Achird", "Zubenelgenubi",
              "Vindemiatrix", "Sadachbia", "Sadaltager", "Sulafat")
    LOCALES = {"en": "en-US", "ru": "ru-RU", "de": "de-DE", "fr": "fr-FR", "es": "es-ES", "it": "it-IT",
               "zh": "zh-CN", "ja": "ja-JP", "ko": "ko-KR"}
    BASE = "https://generativelanguage.googleapis.com/v1beta"

    def headers(self):
        return {"x-goog-api-key": self.key}

    def discover_models(self):
        data = self.call("GET", f"{self.BASE}/models?pageSize=200").json()
        return [m["name"].removeprefix("models/") for m in data.get("models", [])
                if "tts" in m["name"] and "generateContent" in m.get("supportedGenerationMethods", ["generateContent"])]

    @classmethod
    def rank(cls, model_id):
        m = re.fullmatch(r"gemini-(\d+)\.(\d+)-(flash-lite|flash|pro)-tts(-preview)?", model_id)
        if not m:
            return ()
        tier = {"flash-lite": 0, "pro": 1, "flash": 2}[m[3]]
        return (int(m[1]), int(m[2]), 0 if m[4] else 1, tier)

    @classmethod
    def estimate_for(cls, chars, takes=1, mode="preset", model=""):
        seconds = chars * takes / 14  # narration pace, characters per second
        return {"chars": chars * takes, "usd": round(seconds * 0.00225 / 10, 3), "note": cls.price_note}

    def speakers(self, lang=None):
        return {v: ("", "") for v in self.VOICES}

    def setup_voices(self, jobs):
        if self.mode != "design":
            return []
        made: dict[tuple[str, str], str] = {}
        for j in jobs:
            key = (j.description, j.lang)
            if key not in made:
                if not self.model.startswith("gemini-3.8"):
                    raise CloudError(f"Gemini voice design needs a gemini-3.8 model, not {self.model}", "bad_request")
                r = self.call("POST", f"{self.BASE}/voices", {"store": True, "voice": {
                    "model": self.model, "type": "prompted", "display_name": f"folivox-{uuid.uuid4().hex[:8]}",
                    "language_code": self.LOCALES.get(j.lang, "en-US"), "prompted": {"input": j.description}}}).json()
                if not r.get("id"):
                    raise CloudError("Gemini did not return a voice id for the description", "server")
                made[key] = r["id"]
            j.speaker = made[key]
        return list(made.values())

    def teardown_voices(self, ids):
        for i in ids:
            self.call("DELETE", f"{self.BASE}/voices/{i}")

    def synth(self, job: Job) -> bytes:
        voice = job.speaker or "Kore"
        if self.mode != "design" and voice not in self.VOICES:
            raise CloudError(f"Gemini has no voice {voice!r}; choose one of: {', '.join(self.VOICES)}", "bad_request")
        part: dict = {"text": job.text}
        cfg: dict = {"responseModalities": ["AUDIO"]}
        style = job.description if self.mode == "preset" else ""
        if self.model.startswith("gemini-2.5"):  # older request shape: style is a prefix, voice is prebuilt
            if style:
                part["text"] = f"Say in this style ({style}): {job.text}"
            cfg["speechConfig"] = {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}
        else:
            if style:
                part["speech_metadata"] = {"style": style}
            cfg["speechConfig"] = {"voiceConfig": {"voice": voice}}
        r = self.call("POST", f"{self.BASE}/models/{self.model}:generateContent",
                      {"contents": [{"role": "user", "parts": [part]}], "generationConfig": cfg})
        try:
            inline = r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]
            raw = b64(inline["data"])
        except (KeyError, IndexError, TypeError):
            raise CloudError("Gemini returned no audio (the text may have been blocked by its safety filters)",
                             "bad_request") from None
        if raw[:4] == b"RIFF":
            return raw
        m = re.search(r"rate=(\d+)", str(inline.get("mimeType", "")))
        return pcm_to_wav(raw, int(m.group(1)) if m else 24000)


class OpenAIVoice(CloudGenerator):
    """OpenAI ``/audio/speech``. ``gpt-4o-mini-tts`` follows free-text instructions (tone, pace, accent)."""

    name, label, modes, languages = "openai", "OpenAI", ("preset",), LANGS
    style = True
    blurb = (
        "13 ready-made voices; a style note steers tone and pace ('audiobook narration, calm, steady pace'). "
        'No voice-from-description. Simple, reliable and cheap.'
    )
    key_env = "OPENAI_API_KEY"
    price_note = ("gpt-4o-mini-tts: roughly $0.015 per minute of audio (billed in tokens); tts-1: $15 per million "
                  "characters; tts-1-hd: $30.")
    terms_url = "https://openai.com/policies/terms-of-use"
    docs_url = "https://developers.openai.com/api/docs/guides/text-to-speech"
    max_chars = 4096
    models = (_model("gpt-4o-mini-tts", "GPT-4o mini TTS", "newest; follows style instructions"),
              _model("tts-1-hd", "TTS-1 HD", "no instructions"), _model("tts-1", "TTS-1", "cheapest, no instructions"))
    VOICES = ("alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer", "verse",
              "marin", "cedar")
    CLASSIC = ("alloy", "ash", "coral", "echo", "fable", "onyx", "nova", "sage", "shimmer")  # tts-1 / tts-1-hd

    def __init__(self, base_url: str = "https://api.openai.com/v1", **kw):
        super().__init__(**kw)
        self.base_url = base_url.rstrip("/")

    def headers(self):
        return {"Authorization": f"Bearer {self.key}"}

    def discover_models(self):
        data = self.call("GET", f"{self.base_url}/models").json()
        return [m["id"] for m in data.get("data", []) if re.fullmatch(r"gpt-[a-z0-9.\-]*tts", m["id"])]

    @classmethod
    def rank(cls, model_id):
        # the undated alias of a gpt-*-tts model; a higher generation number wins
        nums = [int(n) for n in re.findall(r"\d+", model_id)]
        return (nums or [0], model_id) if re.fullmatch(r"gpt-[a-z0-9.\-]*tts", model_id) else ()

    @classmethod
    def estimate_for(cls, chars, takes=1, mode="preset", model=""):
        n = chars * takes
        usd = n / 1e6 * (30 if model == "tts-1-hd" else 15) if model.startswith("tts-1") else n / 14 / 60 * 0.015
        return {"chars": n, "usd": round(usd, 3), "note": cls.price_note}

    def speakers(self, lang=None):
        voices = self.VOICES if self.model.startswith("gpt-") else self.CLASSIC
        return {v: ("", "") for v in voices}

    def synth(self, job: Job) -> bytes:
        voice = job.speaker or "coral"
        if voice not in self.speakers():
            raise CloudError(f"{self.model} has no voice {voice!r}; choose one of: {', '.join(self.speakers())}",
                             "bad_request")
        payload = {"model": self.model, "input": job.text, "voice": voice, "response_format": "wav"}
        if job.description and self.model.startswith("gpt-"):  # tts-1 rejects `instructions`
            payload["instructions"] = job.description
        return self.call("POST", f"{self.base_url}/audio/speech", payload).body


class ElevenLabs(CloudGenerator):
    """ElevenLabs: preset voices via text-to-speech, Voice Design previews from a text description."""

    name, label, modes, languages = "elevenlabs", "ElevenLabs", ("preset", "design"), LANGS
    style = True  # eleven_v3 / eleven_v4 read audio tags such as "[calm]" as direction, not as words
    blurb = (
        'Very natural voices. Describe a new voice in words and get 3 different candidates at once, or '
        'pick a ready-made one. The free plan is for personal, non-commercial use; audiobooks you sell '
        'need a paid plan.'
    )
    key_env = "ELEVENLABS_API_KEY"
    price_note = ("Pay-as-you-go list price $0.04–0.08 per 1,000 characters depending on the model (plans include "
                  "monthly credits). Free plan: personal non-commercial use, library voices are not available through "
                  "the API. Voice Design bills the preview text once per 3 previews.")
    terms_url = "https://elevenlabs.io/terms-of-use"
    docs_url = "https://elevenlabs.io/docs/api-reference/text-to-voice/design"
    max_chars = 10000
    BASE = "https://api.elevenlabs.io"
    models = (_model("eleven_v4", "Eleven v4", "newest, 90+ languages"), _model("eleven_v3", "Eleven v3", "expressive"),
              _model("eleven_multilingual_v2", "Multilingual v2", "29 languages, stable"),
              _model("eleven_flash_v2_5", "Flash v2.5", "fast and cheap"))
    DESIGN_MODELS = ("eleven_ttv_v3", "eleven_multilingual_ttv_v2")
    PRICE_PER_1K = {"eleven_v4": 0.08, "eleven_v4_turbo": 0.04, "eleven_v3": 0.08, "eleven_multilingual_v2": 0.08}
    LIMITS = {"eleven_v4": 10000, "eleven_v4_turbo": 10000, "eleven_v3": 5000, "eleven_multilingual_v2": 10000,
              "eleven_flash_v2_5": 40000}

    def __init__(self, design_model: str = "eleven_ttv_v3", **kw):
        super().__init__(**kw)
        self.design_model = design_model
        self.names = {}

    def headers(self):
        return {"xi-api-key": self.key}

    def discover_models(self):
        data = self.call("GET", f"{self.BASE}/v1/models").json().get("data", [])
        return [m["model_id"] for m in data if m.get("can_do_text_to_speech")] if isinstance(data, list) else []

    @classmethod
    def rank(cls, model_id):
        m = re.fullmatch(r"eleven_v(\d+)", model_id)  # plain flagship line; turbo / flash / conversational skipped
        return (int(m[1]),) if m else ()

    @classmethod
    def estimate_for(cls, chars, takes=1, mode="preset", model=""):
        n = chars * (math.ceil(takes / 3) if mode == "design" else takes)
        return {"chars": n, "usd": round(n / 1000 * cls.PRICE_PER_1K.get(model, 0.08 if not model else 0.04), 3),
                "note": cls.price_note}

    def check_text(self, text):
        self.max_chars = self.LIMITS.get(self.model, 10000)
        super().check_text(text)

    def speakers(self, lang=None):
        if self._speakers is None:
            out, token = {}, None
            for _ in range(5):  # at most 500 voices
                q = {"page_size": 100, "category": "premade", **({"next_page_token": token} if token else {})}
                data = self.call("GET", f"{self.BASE}/v2/voices?{urllib.parse.urlencode(q)}").json()
                for v in data.get("voices", []):
                    sex = {"female": "f", "male": "m"}.get((v.get("labels") or {}).get("gender", ""), "")
                    out[v["voice_id"]] = ("", sex)
                    self.names[v["voice_id"]] = v.get("name", v["voice_id"])
                token = data.get("next_page_token")
                if not data.get("has_more") or not token:
                    break
            self._speakers = out
        return self._speakers

    def synth(self, job: Job) -> bytes:
        if not job.speaker:
            raise CloudError("ElevenLabs: pick a voice (preset mode needs a voice id)", "bad_request")
        text = job.text
        if job.description and re.fullmatch(r"eleven_v[34]\w*", self.model):
            text = f"[{job.description.strip('[] ')}] {job.text}"
        payload = {"text": text, "model_id": self.model, "seed": job.seed % 4294967295}
        url = f"{self.BASE}/v1/text-to-speech/{urllib.parse.quote(job.speaker, safe='')}?output_format=pcm_24000"
        return pcm_to_wav(self.call("POST", url, payload).body, 24000)

    def generate(self, jobs, progress=None):
        import time

        if self.mode != "design":
            return super().generate(jobs, progress)
        groups: dict[tuple[str, str], list[Job]] = {}
        for j in jobs:
            self.check_lang(j.lang)
            if not 100 <= len(j.text) <= 1000:
                raise CloudError("ElevenLabs Voice Design needs a text of 100–1000 characters", "bad_request")
            if len(j.description) < 20:
                raise CloudError("ElevenLabs Voice Design needs a description of at least 20 characters",
                                 "bad_request")
            groups.setdefault((j.text, j.description), []).append(j)
        for (text, description), group in groups.items():
            for i in range(0, len(group), 3):  # one request returns 3 previews, billed once
                chunk, t0 = group[i:i + 3], time.time()
                data = self.call("POST", f"{self.BASE}/v1/text-to-voice/design?output_format=pcm_24000", {
                    "voice_description": description, "text": text, "model_id": self.design_model}).json()
                previews = data.get("previews") or []
                if len(previews) < len(chunk):
                    raise CloudError("ElevenLabs returned fewer voice previews than requested", "server")
                for j, pv in zip(chunk, previews, strict=False):
                    raw = b64(pv.get("audio_base_64", ""))
                    media = str(pv.get("media_type", ""))
                    Path(j.out).write_bytes(to_wav(raw) if "mpeg" in media or raw[:4] == b"RIFF"
                                            else pcm_to_wav(raw, 24000))
                    if progress:
                        progress(j, (time.time() - t0) / len(chunk))
        return [j.out for j in jobs]

    def map_error(self, resp):
        if resp.status == 409:  # a preview for this account is still being generated
            return CloudError("ElevenLabs is still busy with an earlier voice preview", "server", 3)
        return super().map_error(resp)


class Cartesia(CloudGenerator):
    """Cartesia Sonic: preset voices; *localize* gives a voice the native accent of the target language; *clone*
    copies one of your own voices from a sample. The API has no text-based voice design."""

    name, label, languages = "cartesia", "Cartesia", LANGS
    modes = ("preset", "localize", "clone")
    mode_labels = {"preset": "Pick a voice", "localize": "Same voice, native accent of the language",
                   "clone": "Clone one of my voices"}
    blurb = (
        "Clean, fast voices in 40+ languages. Pick a voice, give it the native accent of your book's "
        'language, or clone one of your own voices from your recording. No voice-from-description. '
        'Cloning needs a paid plan.'
    )
    key_env = "CARTESIA_API_KEY"
    price_note = ("1 credit per character: free plan 20,000 credits a month, Pro $5 for 100,000. Localizing a voice "
                  "costs about 225 credits, cloning needs a paid plan. Commercial use of the output needs a paid "
                  "plan; the terms forbid using output to develop competing models.")
    terms_url = "https://cartesia.ai/legal/terms.html"
    docs_url = "https://docs.cartesia.ai/api-reference/tts/bytes"
    max_chars = 5000
    BASE = "https://api.cartesia.ai"
    VERSION = "2026-08-14"
    models = (_model("sonic-3.6", "Sonic 3.6", "newest, 44 languages"), _model("sonic-3.5", "Sonic 3.5"),
              _model("sonic-3", "Sonic 3"), _model("sonic-latest", "Sonic latest", "alias that moves with releases"))

    def headers(self):
        return {"Authorization": f"Bearer {self.key}", "Cartesia-Version": self.VERSION}

    @classmethod
    def estimate_for(cls, chars, takes=1, mode="preset", model=""):
        n = chars * takes + (225 if mode == "localize" else 0)
        return {"chars": n, "usd": round(n * 5 / 100000, 3), "note": cls.price_note}

    def speakers(self, lang=None):
        key = lang or ""
        cache = self.__dict__.setdefault("_by_lang", {})
        if key not in cache:
            out, after = {}, None
            for _ in range(3):  # at most 300 voices
                q = {"limit": 100, **({"language": lang} if lang else {}),
                     **({"starting_after": after} if after else {})}
                data = self.call("GET", f"{self.BASE}/voices?{urllib.parse.urlencode(q)}").json()
                for v in data.get("data", []):
                    sex = {"feminine": "f", "masculine": "m"}.get(v.get("gender", ""), "")
                    out[v["id"]] = (lang or v.get("language") or "", sex)
                    self.names[v["id"]] = v.get("name", v["id"])
                rows = data.get("data") or []
                if not data.get("has_more") or not rows:
                    break
                after = rows[-1]["id"]
            cache[key] = out
        return cache[key]

    def accent_for(self, lang: str) -> str:
        accents = self.call("GET", f"{self.BASE}/accents?is_localizable=true").json().get("accents", [])
        mine = [a for a in accents if a.get("language") == lang]
        mine.sort(key=lambda a: not a.get("is_locale_default"))
        if not mine:
            raise CloudError(f"Cartesia cannot localize a voice to {lang!r}", "bad_request")
        return mine[0]["id"]

    def setup_voices(self, jobs):
        if self.mode == "preset":
            return []
        made: dict[tuple, str] = {}
        name = f"folivox-{uuid.uuid4().hex[:8]}"
        for j in jobs:
            key = (j.speaker, str(j.reference), j.lang)
            if key in made:
                j.speaker = made[key]
                continue
            if self.mode == "localize":
                if not j.speaker:
                    raise CloudError("Cartesia: pick the voice to localize", "bad_request")
                r = self.call("POST", f"{self.BASE}/voices/localize",
                              {"voice_id": j.speaker, "name": name, "accent": self.accent_for(j.lang)}).json()
            else:
                if not j.reference or not Path(j.reference).exists():
                    raise CloudError("Cartesia clone: choose one of your own voices as the sample", "bad_request")
                r = self.upload_clone(Path(j.reference), name, j.lang)
            if not r.get("id"):
                raise CloudError("Cartesia did not return a voice id", "server")
            made[key] = j.speaker = r["id"]
        return list(made.values())

    def upload_clone(self, clip: Path, name: str, lang: str) -> dict:
        boundary = uuid.uuid4().hex

        def part(field, value, filename=None):
            head = f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"'
            head += f'; filename="{filename}"\r\nContent-Type: audio/wav' if filename else ""
            return (head + "\r\n\r\n").encode() + (value if isinstance(value, bytes) else value.encode()) + b"\r\n"

        body = part("clip", file_as_wav(clip), "voice.wav") + part("name", name) + part("language", lang)
        body += f"--{boundary}--\r\n".encode()
        headers = {**self.headers(), "Content-Type": f"multipart/form-data; boundary={boundary}"}
        resp = self.transport("POST", f"{self.BASE}/voices/clone", headers, body, 120)
        if resp.status >= 300:
            raise self.map_error(resp)
        return resp.json()

    def teardown_voices(self, ids):
        for i in ids:
            self.call("DELETE", f"{self.BASE}/voices/{i}")

    def synth(self, job: Job) -> bytes:
        if not job.speaker:
            raise CloudError("Cartesia: pick a voice (a voice id)", "bad_request")
        payload = {"model_id": self.model, "transcript": job.text, "voice": {"id": job.speaker},
                   "language": job.lang,
                   "output_format": {"container": "wav", "encoding": "pcm_s16le", "sample_rate": 24000}}
        return self.call("POST", f"{self.BASE}/tts/bytes", payload).body
