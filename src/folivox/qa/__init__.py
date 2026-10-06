"""Quality check of synthesized takes: re-transcribe with Whisper and compare with the source."""

from __future__ import annotations

import re

from folivox import lang as languages


def canonical(text: str, lang: str = "ru") -> str:
    """Text reduced for comparison: numbers as words, lowercase, no punctuation (per language)."""
    return languages.get(lang).canonical(text)


def strip_hallucinations(hypothesis: str, reference: str, lang: str = "ru") -> str:
    """Drop trailing Whisper hallucinations that are not part of the reference text."""
    patterns = [re.compile(rf"\s*{h}\s*$", re.IGNORECASE) for h in languages.get(lang).hallucinations]
    ref = reference.lower()
    changed = True
    while changed:
        changed = False
        for rx in patterns:
            m = rx.search(hypothesis)
            if m and m.group(0).strip().lower().rstrip(".!?…。！？") not in ref:
                hypothesis = hypothesis[: m.start()]
                changed = True
    return hypothesis.strip()
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


def cer(reference: str, hypothesis: str, lang: str = "ru") -> float:
    """Character error rate between canonical forms (0 = identical)."""
    ref, hyp = canonical(reference, lang), canonical(hypothesis, lang)
    if not ref:
        return 0.0 if not hyp else 1.0
    return levenshtein(ref, hyp) / len(ref)


def threshold_for(reference: str, base: float, lang: str = "ru") -> float:
    """Short colloquial lines («Не-а.», «Покажь.») are where Whisper itself errs most:
    one wrong letter is already 20–30 % CER, so retakes would only burn time."""
    n = len(canonical(reference, lang))
    if lang in ("zh", "ja", "ko"):
        n *= 3  # one CJK character carries about as much as three letters
    if n < 15:
        return max(base, 0.35)
    if n < 40:
        return max(base, 0.15)
    return base


def score(reference: str, hypothesis: str, duration: float, lang: str = "ru") -> float:
    """Lower is better. CER plus a penalty for speaking rate outside the language's plausible range
    (swallowed words, long silence, babbling) even if Whisper is forgiving."""
    s = cer(reference, strip_hallucinations(hypothesis, reference, lang), lang)
    n = len(canonical(reference, lang))
    lo, hi = languages.get(lang).cps
    if duration > 0 and n >= (20 if lo > 5 else 8):
        cps = n / duration
        if cps < lo:
            s += (lo - cps) / lo
        elif cps > hi:
            s += (cps - hi) / hi
    return round(s, 4)
