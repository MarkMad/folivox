"""Per-language text processing: normalisation, sentence splitting, QA canonical form, headings.

Languages register themselves on import; :func:`get` returns the module for a book language.
"""

from __future__ import annotations

import importlib

from folivox.lang.base import CJKLanguage, Language, LatinLanguage, has_speech

__all__ = ["CJKLanguage", "Language", "LatinLanguage", "available", "get", "has_speech", "register"]

# CosyVoice 3 languages. Each code maps to the module folivox.lang.<code>.
SUPPORTED = ("ru", "en", "de", "fr", "es", "it", "zh", "ja", "ko")

_registry: dict[str, Language] = {}


def register(lang: Language) -> Language:
    _registry[lang.code] = lang
    return lang


def _load_all() -> None:
    for code in SUPPORTED:
        if code not in _registry:
            importlib.import_module(f"folivox.lang.{code}")


def available() -> list[Language]:
    _load_all()
    return [_registry[c] for c in SUPPORTED if c in _registry] + [
        v for k, v in _registry.items() if k not in SUPPORTED]


def normalize_code(code: str | None) -> str:
    """'ru-RU' / 'RUS' / 'zh_Hans' → 'ru' / 'ru' / 'zh'."""
    code = (code or "").strip().lower().replace("_", "-").split("-")[0]
    return {"rus": "ru", "eng": "en", "deu": "de", "ger": "de", "fra": "fr", "fre": "fr", "spa": "es",
            "ita": "it", "zho": "zh", "chi": "zh", "cmn": "zh", "jpn": "ja", "kor": "ko"}.get(code, code)


def get(code: str | None) -> Language:
    code = normalize_code(code)
    if code not in _registry:
        try:
            importlib.import_module(f"folivox.lang.{code}")
        except ImportError:
            pass
    if code not in _registry:
        raise ValueError(f"Unsupported language {code!r}; supported: {', '.join(SUPPORTED)}")
    return _registry[code]
