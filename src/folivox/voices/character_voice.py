"""Voice-design prompts for the characters of a book, written from the character list.

A voice-design model needs an English description of the voice. For each character a text LLM writes three,
from plain to detailed, so that models of any level understand at least the first and a strong model can use the
finer one; a weak model simply ignores words it does not understand. The prompts never contain the character's
name, the plot or a real person, and a character is asked to sound clearly different from the voices described
before. Without an LLM (or when its answer is unusable) a plain description is built from gender and age.

The user listens to the generated takes and chooses; nothing here picks a voice automatically.
"""

from __future__ import annotations

from dataclasses import dataclass

from folivox.markup import Markup
from folivox.markup_llm import LANG_NAMES, Bible, Character, extract_json
from folivox.voices.suggest import BAD

TIERS = ("simple", "standard", "detailed")
LIMITS = {"simple": 150, "standard": 320, "detailed": 560}  # characters; cloud design prompts are short

SYSTEM = ("You write short voice descriptions for a text-to-speech voice-design model. You describe only how a "
          "voice sounds. You never name or hint at a real person, an actor, a celebrity or a brand. You answer "
          "with one JSON object and nothing else.")

PROMPT = """Write three English descriptions of the speaking voice of ONE character from a book, for a voice-design
model. The audience for the descriptions is an AI model, so use plain, common words (no poetry, no jargon).

Character:
- gender: {gender}
- age: {age}
- how they speak: {traits}
- role in the story: {role}
- relations: {relations}
- the book is in: {language}; the voice is that of a native speaker of {language}
- a few of their lines (only to feel their manner, never quote them): {lines}

Voices already described for other characters (this one must clearly differ in pitch, pace or manner):
{others}

Reply with this JSON:
{{"simple": "...", "standard": "...", "detailed": "..."}}

- "simple": ONE short sentence, at most {n_simple} characters: sex, age range, pace and mood only. Every word must be
  one a basic model understands.
- "standard": at most {n_standard} characters: add pitch and timbre, speaking style and that they are a native
  {language} speaker.
- "detailed": at most {n_detailed} characters: also the emotional range and small habits (pauses, breathiness,
  warmth, edge). Still plain words.
Do not use the character's name. Do not describe the story, clothes or surroundings. Do not write "sounds like"."""

GENDER = {"f": "female", "m": "male", "n": "neutral or a group", "": "not known (choose what fits the lines)"}
AGE = {"child": "a child", "young": "young adult", "adult": "adult", "old": "elderly", "": "not known"}
FALLBACK_AGE = {"child": "child", "young": "young", "adult": "adult", "old": "elderly", "": "adult"}
FALLBACK_WHO = {"f": "woman", "m": "man", "n": "person", "": "person"}


@dataclass
class VoiceIdeas:
    prompts: dict[str, str]
    from_llm: bool


def _ascii(s: str) -> str:
    return s if s and all(ord(c) < 128 for c in s) else ""


def fallback_prompts(c: Character, language: str) -> dict[str, str]:
    """A plain description from gender and age (and traits written in English), when no LLM answer is usable."""
    who = FALLBACK_WHO.get(c.gender, "person")
    age = FALLBACK_AGE.get(c.age, "adult")
    if age == "child" and who in ("woman", "man"):
        who = "girl" if who == "woman" else "boy"
    traits = _ascii(c.traits.split(";")[0].strip())
    simple = f"A {age} {who}, speaking at a natural pace, calm and clear."
    standard = (f"A {age} {who}, a native {language} speaker, natural speaking pace"
                f"{', ' + traits if traits else ', clear and steady'}, close to the microphone, no background noise.")
    detailed = standard[:-1] + ", with natural pauses and a believable, lightly expressive delivery."
    return {"simple": simple, "standard": standard, "detailed": detailed}


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.replace("```", " ").split()).strip(" \"'")
    if len(text) <= limit:
        return text
    cut = text[:limit]
    return cut[: cut.rfind(". ") + 1] if ". " in cut else cut[: cut.rfind(" ")].rstrip(" ,;") + "."


def _valid(text: str, c: Character) -> bool:
    if len(text) < 15 or BAD.search(text):
        return False
    low = text.casefold()
    return not any(n.casefold() in low for n in c.names() if len(n) >= 3)


def ideas_for(c: Character, lang: str, llm, others: list[str] | None = None,
              lines: list[str] | None = None) -> VoiceIdeas:
    """Three prompts for one character. Tiers the LLM got wrong are replaced by the plain fallback."""
    language = LANG_NAMES.get(lang, lang)
    base = fallback_prompts(c, language)
    if llm is None:
        return VoiceIdeas(base, False)
    prompt = PROMPT.format(
        gender=GENDER.get(c.gender, GENDER[""]), age=AGE.get(c.age, c.age or "not known"),
        traits=c.traits or "not known", role="main character" if c.role == "main" else "minor character",
        relations=", ".join(f"{r.get('kind', '')} of {r.get('with', '')}" for r in c.relations[:4]) or "none",
        language=language, lines=" | ".join(x[:120] for x in (lines or [])[:3]) or "none",
        others="\n".join(f"- {o}" for o in (others or [])[-8:]) or "none", n_simple=LIMITS["simple"],
        n_standard=LIMITS["standard"], n_detailed=LIMITS["detailed"])
    try:
        reply = llm.complete_json(prompt, system=SYSTEM, temperature=0.6)
        data = extract_json(reply)
    except (ValueError, OSError):
        return VoiceIdeas(base, False)
    out, good = {}, 0
    for tier in TIERS:
        text = _clip(str(data.get(tier) or ""), LIMITS[tier])
        if _valid(text, c):
            out[tier] = text
            good += 1
        else:
            out[tier] = base[tier]
    return VoiceIdeas(out, good > 0)


def speaker_lines(markup: Markup, chapters: list, speaker: int, limit: int = 3, max_chars: int = 220) -> list[str]:
    """Some of the character's own lines, for the voice-design sample text and as a hint to the LLM."""
    out: list[str] = []
    for ci in sorted(markup.chapters):
        if ci >= len(chapters):
            continue
        for s in markup.chapters[ci].spans:
            if s.speaker != speaker or s.block >= len(chapters[ci].blocks):
                continue
            text = chapters[ci].blocks[s.block].text[s.start:s.end].strip().strip("—–―").strip()
            if 25 <= len(text) <= max_chars and text not in out:
                out.append(text)
            if len(out) >= limit:
                return out
    return out


def design_all(bible: Bible, lang: str, llm, markup: Markup | None = None, chapters: list | None = None,
               speakers: set[int] | None = None, regenerate: bool = False, progress=None) -> int:
    """Fill ``voice_prompts`` of the speaking characters (busiest first, so later ones are told how to differ).
    Returns how many characters got new prompts."""
    cast = [c for c in sorted(bible.characters, key=lambda c: -c.lines)
            if c.id and (speakers is None or c.id in speakers)]
    redo = {c.id for c in cast if regenerate or (speakers and c.id in speakers)}
    others = [c.voice_prompts["standard"] for c in cast if c.voice_prompts.get("standard") and c.id not in redo]
    done = 0
    for n, c in enumerate(cast):
        if c.voice_prompts and c.id not in redo:
            continue
        lines = speaker_lines(markup, chapters, c.id) if markup is not None and chapters else []
        ideas = ideas_for(c, lang, llm, others, lines)
        c.voice_prompts = ideas.prompts
        others.append(ideas.prompts["standard"])
        done += 1
        if progress:
            progress("voices", n + 1, len(cast), c.name)
    return done


def sample_texts(markup: Markup | None, chapters: list | None, speaker: int, lang: str) -> list[str]:
    """What the generated voice reads: the character's own lines, else the built-in calm sample of the language."""
    from folivox.voices.design import safe_texts

    own = speaker_lines(markup, chapters, speaker, limit=2, max_chars=240) if markup is not None and chapters else []
    return own or safe_texts(lang)[:1]
