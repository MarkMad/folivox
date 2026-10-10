"""Gemini, OpenAI, ElevenLabs and Cartesia voice generators (endpoints and models checked against the
providers' documentation in October 2026; see CONTRIBUTING for how to add another)."""

from __future__ import annotations

import math
import re
import urllib.parse
from pathlib import Path

from folivox.voicegen import Job
from folivox.voicegen.cloud import CloudError, CloudGenerator, b64, pcm_to_wav, to_wav

LANGS = ("en", "ru", "de", "fr", "es", "it", "zh", "ja", "ko")


class Gemini(CloudGenerator):
    """Gemini API speech generation: 30 preset voices, language auto-detected, style given as a note."""

    name, label, modes, languages = "gemini", "Gemini API", ("preset",), LANGS
    key_env = "GEMINI_API_KEY"
    price_note = ("Paid tier about $0.0023 per 10 s of audio (gemini-3.8-flash-tts, doubles in 2027); a free tier "
                  "exists, but Google may then use your text for product improvement.")
    terms_url = "https://ai.google.dev/gemini-api/terms"
    docs_url = "https://ai.google.dev/gemini-api/docs/generate-content/speech-generation"
    max_chars = 4000
    VOICES = ("Zephyr", "Puck", "Charon", "Kore", "Fenrir", "Leda", "Orus", "Aoede", "Callirrhoe", "Autonoe",
              "Enceladus", "Iapetus", "Umbriel", "Algieba", "Despina", "Erinome", "Algenib", "Rasalgethi",
              "Laomedeia", "Achernar", "Alnilam", "Schedar", "Gacrux", "Pulcherrima", "Achird", "Zubenelgenubi",
              "Vindemiatrix", "Sadachbia", "Sadaltager", "Sulafat")
    BASE = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self, model: str = "gemini-3.8-flash-tts", **kw):
        super().__init__(**kw)
        self.model = model

    def headers(self):
        return {"x-goog-api-key": self.key}

    @classmethod
    def estimate_for(cls, chars, takes=1, mode="preset"):
        n = chars * takes
        seconds = n / 14  # narration pace, characters per second
        return {"chars": n, "usd": round(seconds * 0.00225 / 10, 3), "note": cls.price_note}

    def speakers(self, lang=None):
        return {v: ("", "") for v in self.VOICES}

    def synth(self, job: Job) -> bytes:
        voice = job.speaker or "Kore"
        if voice not in self.VOICES:
            raise CloudError(f"Gemini has no voice {voice!r}; choose one of: {', '.join(self.VOICES)}", "bad_request")
        part: dict = {"text": job.text}
        cfg: dict = {"responseModalities": ["AUDIO"]}
        if self.model.startswith("gemini-2.5"):  # older request shape: style is a prefix, voice is prebuilt
            if job.description:
                part["text"] = f"Say in this style ({job.description}): {job.text}"
            cfg["speechConfig"] = {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}
        else:
            if job.description:
                part["speech_metadata"] = {"style": job.description}
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
    """OpenAI ``/audio/speech``. ``gpt-4o-mini-tts`` also follows free-text style instructions."""

    name, label, modes, languages = "openai", "OpenAI", ("preset",), LANGS
    key_env = "OPENAI_API_KEY"
    price_note = ("gpt-4o-mini-tts: roughly $0.015 per minute of audio (billed in tokens); tts-1: $15 per million "
                  "characters; tts-1-hd: $30.")
    terms_url = "https://openai.com/policies/terms-of-use"
    docs_url = "https://developers.openai.com/api/docs/guides/text-to-speech"
    max_chars = 4096
    VOICES = ("alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer", "verse",
              "marin", "cedar")
    CLASSIC = ("alloy", "ash", "coral", "echo", "fable", "onyx", "nova", "sage", "shimmer")  # tts-1 / tts-1-hd

    def __init__(self, model: str = "gpt-4o-mini-tts", base_url: str = "https://api.openai.com/v1", **kw):
        super().__init__(**kw)
        self.model, self.base_url = model, base_url.rstrip("/")

    def headers(self):
        return {"Authorization": f"Bearer {self.key}"}

    @classmethod
    def estimate_for(cls, chars, takes=1, mode="preset"):
        n = chars * takes
        return {"chars": n, "usd": round(n / 14 / 60 * 0.015, 3), "note": cls.price_note}

    def speakers(self, lang=None):
        voices = self.VOICES if self.model.startswith("gpt-4o") else self.CLASSIC
        return {v: ("", "") for v in voices}

    def synth(self, job: Job) -> bytes:
        voice = job.speaker or "coral"
        if voice not in self.speakers():
            raise CloudError(f"{self.model} has no voice {voice!r}; choose one of: {', '.join(self.speakers())}",
                             "bad_request")
        payload = {"model": self.model, "input": job.text, "voice": voice, "response_format": "wav"}
        if job.description and self.model.startswith("gpt-4o"):  # tts-1 rejects `instructions`
            payload["instructions"] = job.description
        return self.call("POST", f"{self.base_url}/audio/speech", payload).body


class ElevenLabs(CloudGenerator):
    """ElevenLabs: preset voices via text-to-speech, Voice Design previews from a text description."""

    name, label, modes, languages = "elevenlabs", "ElevenLabs", ("preset", "design"), LANGS
    key_env = "ELEVENLABS_API_KEY"
    price_note = ("Pay-as-you-go about $0.08 per 1,000 characters (eleven_multilingual_v2); plans include monthly "
                  "credits. Free plan: personal non-commercial use, library voices are not available through the "
                  "API. Voice Design bills the preview text once per 3 previews.")
    terms_url = "https://elevenlabs.io/terms-of-use"
    docs_url = "https://elevenlabs.io/docs/api-reference/text-to-voice/design"
    max_chars = 5000
    BASE = "https://api.elevenlabs.io"
    USD_PER_CHAR = 0.00008

    def __init__(self, model: str = "eleven_multilingual_v2", design_model: str = "eleven_multilingual_ttv_v2", **kw):
        super().__init__(**kw)
        self.model, self.design_model = model, design_model
        self.names = {}

    def headers(self):
        return {"xi-api-key": self.key}

    @classmethod
    def estimate_for(cls, chars, takes=1, mode="preset"):
        n = chars * (math.ceil(takes / 3) if mode == "design" else takes)
        return {"chars": n, "usd": round(n * cls.USD_PER_CHAR, 3), "note": cls.price_note}

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
        if self.mode == "design":
            raise CloudError("internal: design takes go through generate()", "bad_request")
        if not job.speaker:
            raise CloudError("ElevenLabs: pick a voice (preset mode needs a voice id)", "bad_request")
        payload = {"text": job.text, "model_id": self.model, "seed": job.seed % 4294967295}
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
    """Cartesia Sonic: preset voices only (the API documents voice cloning and localisation, not text design)."""

    name, label, modes, languages = "cartesia", "Cartesia", ("preset",), LANGS
    key_env = "CARTESIA_API_KEY"
    price_note = ("1 credit per character: free plan 20,000 credits a month, Pro $5 for 100,000. Commercial use of "
                  "the output needs a paid plan; the terms forbid using output to develop competing models.")
    terms_url = "https://cartesia.ai/legal/terms.html"
    docs_url = "https://docs.cartesia.ai/api-reference/tts/bytes"
    max_chars = 5000
    BASE = "https://api.cartesia.ai"
    VERSION = "2026-08-14"

    def __init__(self, model: str = "sonic-3.6", **kw):
        super().__init__(**kw)
        self.model = model
        self.names = {}

    def headers(self):
        return {"Authorization": f"Bearer {self.key}", "Cartesia-Version": self.VERSION}

    @classmethod
    def estimate_for(cls, chars, takes=1, mode="preset"):
        n = chars * takes
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

    def synth(self, job: Job) -> bytes:
        if not job.speaker:
            raise CloudError("Cartesia: pick a voice (a voice id)", "bad_request")
        payload = {"model_id": self.model, "transcript": job.text, "voice": {"id": job.speaker},
                   "language": job.lang,
                   "output_format": {"container": "wav", "encoding": "pcm_s16le", "sample_rate": 24000}}
        return self.call("POST", f"{self.BASE}/tts/bytes", payload).body
