"""Stress marks and ё restoration via ruaccent (lazy, optional).

Modes:
  ``none`` — leave text as is;
  ``yo``   — restore ё only (safe; default);
  ``all``  — ё + combining acute accent (U+0301) after every stressed vowel. Experimental: CosyVoice 3
             was not trained with Russian stress marks, so check by ear before using on a whole book.
"""

from __future__ import annotations

import re
from functools import lru_cache

MODES = ("none", "yo", "all")
ACUTE = "́"


class StressUnavailable(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _model():
    try:
        from ruaccent import RUAccent
    except ImportError as e:  # pragma: no cover - depends on extras
        raise StressUnavailable("ruaccent не установлен: pip install 'folivox[tts]'") from e
    import logging
    import warnings

    from folivox import gpu

    gpu.pin_cudnn()  # onnxruntime (imported by ruaccent) must not bind to another cuDNN on PATH (error 127)
    logging.getLogger("ruaccent").setLevel(logging.ERROR)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        acc = RUAccent()
        acc.load(omograph_model_size="turbo3.1", use_dictionary=True, tiny_mode=False)
    return acc


def from_ruaccent(marked: str, mode: str) -> str:
    """Convert ruaccent's «+vowel» notation into the requested mode."""
    if mode == "all":
        return re.sub(r"\+([АЕЁИОУЫЭЮЯаеёиоуыэюяAEIOUYaeiouy])", lambda m: m.group(1) + ACUTE, marked).replace(
            "ё" + ACUTE, "ё").replace("Ё" + ACUTE, "Ё")
    return marked.replace("+", "")


def apply(text: str, mode: str = "yo") -> str:
    if mode == "none" or not re.search(r"[а-яё]", text, re.IGNORECASE):
        return text
    if mode not in MODES:
        raise ValueError(f"unknown stress mode {mode!r}; expected one of {MODES}")
    # ruaccent treats «+» as a stress mark; protect literal pluses (rare after normalisation)
    marked = _model().process_all(text.replace("+", " плюс "))
    out = from_ruaccent(marked, mode)
    return _restore_case(text, out) if mode == "yo" else out


def _restore_case(orig: str, out: str) -> str:
    """ruaccent keeps letters but be defensive: only accept е→ё changes, never rewrites."""
    if len(orig) != len(out):
        return out
    chars = []
    for a, b in zip(orig, out, strict=True):
        if a == b or (a in "еЕ" and b in "ёЁ"):
            chars.append(b)
        else:
            chars.append(a)
    return "".join(chars)


def strip_marks(text: str) -> str:
    return text.replace(ACUTE, "").replace("+", "")
