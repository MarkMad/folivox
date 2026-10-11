"""Create reference voices with a voice generator (e.g. Qwen3-TTS VoiceDesign).

Workflow: a generator reads short "safe" texts several times → Whisper scores every take →
the best takes (trimmed, normalised) are offered as zero-shot prompts for the main TTS engine.
Accent and rhythm of the prompt are copied by the clone, so judge the clone, not the take.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from folivox.voices import PACKAGE_DIR

MIN_SECONDS, MAX_SECONDS = 6.0, 16.0


def safe_texts(lang: str) -> list[str]:
    data = json.loads((PACKAGE_DIR / "safe_texts.json").read_text(encoding="utf-8"))
    return data.get(lang, [])


@dataclass
class Candidate:
    path: Path
    text: str
    seed: int
    duration: float
    score: float | None
    transcript: str


def generate_takes(generator, texts: list[str], lang: str, out_dir: Path, *, description: str = "",
                   speaker: str = "", takes: int = 3, prefix: str = "take", progress=None,
                   reference: Path | None = None) -> list[Path]:
    from folivox.voicegen import Job

    out_dir.mkdir(parents=True, exist_ok=True)
    jobs = [Job(text, lang, seed=1000 * k + 7, description=description, speaker=speaker,
                out=out_dir / f"{prefix}_t{ti + 1}_{k}.wav", reference=reference)
            for ti, text in enumerate(texts) for k in range(takes)]
    todo = [j for j in jobs if not j.out.exists()]
    if todo:
        generator.generate(todo, progress)
    return [j.out for j in jobs]


def score_takes(paths: list[Path], texts_by_path: dict[Path, str], asr, lang: str) -> list[Candidate]:
    """Trim silence, transcribe and score every take; best first. Takes outside 6–16 s rank last."""
    from folivox.audio import trim_silence
    from folivox.qa import score
    from folivox.voicegen import load_wav

    out = []
    for p in paths:
        audio, sr = load_wav(p)
        audio = trim_silence(audio, sr, threshold_db=-50, margin=0.1)
        dur = len(audio) / sr
        hyp = asr.transcribe(audio, sr) if asr is not None else ""
        sc = score(texts_by_path[p], hyp, dur, lang) if asr is not None else None
        seed = int(re.search(r"_(\d+)\.wav$", p.name).group(1)) if re.search(r"_(\d+)\.wav$", p.name) else 0
        out.append(Candidate(p, texts_by_path[p], seed, dur, sc, hyp))
    in_range = lambda c: MIN_SECONDS <= c.duration <= MAX_SECONDS  # noqa: E731
    return sorted(out, key=lambda c: (not in_range(c), c.score if c.score is not None else 0))


SELECT_PROMPT = """You pick passages from a book to be read aloud as a short voice sample by a
text-to-speech model that makes mistakes on difficult words. From the text below, copy {n}
passages EXACTLY as written (do not change a single character). Each passage:
- {min_chars}–{max_chars} characters (about 10 seconds when read aloud, never longer), two complete
  sentences in a row (a third only if all are very short);
- calm narration: no dialogue, no exclamations, no questions, no strong emotion, no lists or
  enumerations, no headings, no slashes;
- only common everyday words; NO names of people or places, NO numbers or dates, NO abbreviations,
  NO foreign words, NO words whose stress or meaning depends on context (homographs){extra};
- normal punctuation.
Answer with a JSON list of strings and nothing else.

TEXT:
{text}"""

EXTRA_RULES = {"ru": ", no words where е/ё is ambiguous (все/всё, небо/нёбо), no замок, мука, атлас, орган"}


# characters of calm narration that make about 10 seconds of speech (6–16 s is accepted for a sample)
CHAR_RANGE = {"zh": (28, 55), "ja": (35, 65), "ko": (55, 100)}
DEFAULT_RANGE = (90, 150)


def char_range(lang: str) -> tuple[int, int]:
    return CHAR_RANGE.get(lang, DEFAULT_RANGE)


def pick_book_texts(book_text: str, lang: str, llm, n: int = 3, min_chars: int | None = None,
                    max_chars: int | None = None, window: int = 12000) -> list[str]:
    """Ask the LLM for passages and keep only those that really occur in the book and pass checks."""
    lo, hi = char_range(lang)
    min_chars, max_chars = min_chars or lo, max_chars or hi
    found: list[str] = []
    for start in range(0, max(1, len(book_text)), window):
        chunk = book_text[start:start + window]
        prompt = SELECT_PROMPT.format(n=n, min_chars=min_chars, max_chars=max_chars, text=chunk,
                                      extra=EXTRA_RULES.get(lang, ""))
        reply = llm.complete(prompt, temperature=0.2)
        m = re.search(r"\[.*\]", reply, re.S)
        try:
            items = json.loads(m.group(0)) if m else []
        except json.JSONDecodeError:
            items = []
        for s in items:
            s = " ".join(str(s).split())
            if s and s in " ".join(chunk.split()) and is_safe(s, lang, min_chars, max_chars) and s not in found:
                found.append(s)
        if len(found) >= n:
            break
    return found[:n]


def is_safe(text: str, lang: str, min_chars: int | None = None, max_chars: int | None = None) -> bool:
    """Mechanical checks on top of the LLM's judgement."""
    lo, hi = char_range(lang)
    min_chars, max_chars = min_chars or lo, max_chars or hi
    if not min_chars <= len(text) <= max_chars or re.search(r"\d|[!?«»\"“”—/]|\.\.\.|…", text):
        return False
    words = text.split()
    # a capitalised word that does not start a sentence is probably a name
    for prev, w in zip(words, words[1:], strict=False):
        if w[:1].isupper() and not prev.endswith((".", "!", "?")):
            return False
    if lang == "ru" and re.search(r"[A-Za-z]|\b(?:все|замок|замка|мука|муки|атлас|орган)\b", text, re.I):
        return False
    return True
