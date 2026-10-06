"""Quality check of synthesized takes: re-transcribe with Whisper and compare with the source."""

from __future__ import annotations

import re

from folivox.text.normalize import normalize

_NON_WORD = re.compile(r"[^0-9a-zа-я ]+")


def canonical(text: str) -> str:
    """Text reduced for comparison: numbers as words, lowercase, е instead of ё, no punctuation."""
    # Whisper writes times as «7.30»; make them look like «7:30» before normalising
    text = re.sub(r"\b(\d{1,2})\.(\d{2})\b(?!\.\d)", r"\1:\2", text)
    text = normalize(text).lower().replace("ё", "е").replace("\u0301", "")
    text = _NON_WORD.sub(" ", text.replace("-", " "))
    return " ".join(text.split())


def levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def cer(reference: str, hypothesis: str) -> float:
    """Character error rate between canonical forms (0 = identical)."""
    ref, hyp = canonical(reference), canonical(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    return levenshtein(ref, hyp) / len(ref)


# Plausible narration speed, canonical characters per second. Outside → likely a broken take
# (swallowed words, long silence, babbling) even if Whisper is forgiving.
MIN_CPS, MAX_CPS = 7.0, 28.0


def score(reference: str, hypothesis: str, duration: float) -> float:
    """Lower is better. CER plus a penalty for implausible speaking rate."""
    s = cer(reference, hypothesis)
    n = len(canonical(reference))
    if duration > 0 and n >= 20:
        cps = n / duration
        if cps < MIN_CPS:
            s += (MIN_CPS - cps) / MIN_CPS
        elif cps > MAX_CPS:
            s += (cps - MAX_CPS) / MAX_CPS
    return round(s, 4)
