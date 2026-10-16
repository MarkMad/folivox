"""Speech synthesis engines."""

from folivox.providers import Registry

ENGINES: Registry = Registry("tts", default="cosyvoice3")
ENGINES.register("cosyvoice3", "folivox.tts.engine:CosyVoiceEngine",
                 "Fun-CosyVoice3 0.5B: zero-shot cloning, ru en zh ja ko de es fr it", needs="folivox[tts]")
ENGINES.register("fish-s2", "folivox.tts.fish:FishS2Engine",
                 "Fish Audio S2 Pro (optional, Apple Silicon, personal use licence): natural voices, expression tags",
                 needs="folivox engines install s2pro-mlx-8bit")
ENGINES.register("fish-drama3", "folivox.tts.fish:FishDrama3Engine",
                 "Fish Audio Drama 3 (optional, Apple Silicon, 32+ GB): multi-speaker scenes, expression tags",
                 needs="folivox engines install drama3-mlx-4bit")

# Commercial cloud engines: the book text leaves the computer and is billed to your account (see tts/cloud.py).
for _n, _d, _k in (
        ("elevenlabs", "ElevenLabs (cloud, paid): very natural voices, 90+ languages", "ELEVENLABS_API_KEY"),
        ("openai", "OpenAI TTS (cloud, paid): 13 voices, style notes, simple and cheap", "OPENAI_API_KEY"),
        ("gemini", "Gemini API TTS (cloud, paid): 30 voices, style notes, voice from a description",
         "GEMINI_API_KEY"),
        ("cartesia", "Cartesia Sonic (cloud, paid): fast clean voices, 40+ languages, clone your own voice",
         "CARTESIA_API_KEY")):
    ENGINES.register(_n, f"folivox.tts.cloud:{_n}", _d, local=False, needs=_k)
