"""Speech synthesis engines."""

from folivox.providers import Registry

ENGINES: Registry = Registry("tts", default="cosyvoice3")
ENGINES.register("cosyvoice3", "folivox.tts.engine:CosyVoiceEngine",
                 "Fun-CosyVoice3 0.5B: zero-shot cloning, ru en zh ja ko de es fr it", needs="folivox[tts]")
