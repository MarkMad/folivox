"""Ask a text LLM for an English voice-design prompt that suits a book (genre, era, tone, narrator)."""

from __future__ import annotations

import re

SYSTEM = ("You write short voice descriptions for a text-to-speech voice-design model. "
          "You never describe or name a real person, an actor or a celebrity.")

PROMPT = """Read the excerpt of a book and describe, in English, ONE narrator voice that would suit an audiobook
of it. Cover: apparent age range, sex, timbre, pace, warmth/energy, accent{accent}, and the mood that fits the
genre and era. Style: a single paragraph of at most {max_chars} characters, plain words, no quotes, no markdown,
no names of real people, actors or existing audiobook narrators.

Book: {title}{author}
Language of the book: {lang}
Excerpt:
{text}

Answer with the voice description only."""

BAD = re.compile(r"(?i)\b(sounds? like|in the style of|imitat\w+|impersonat\w+|clone of)\b")


def suggest_design_prompt(book_text: str, lang: str, llm, *, title: str = "", author: str = "",
                          max_chars: int = 400, excerpt_chars: int = 3000) -> str:
    """One design prompt (English). Raises ValueError if the LLM returns nothing usable."""
    # the middle of the first chapters says more about tone than a title page
    text = " ".join(book_text.split())
    start = min(len(text) // 10, 2000)
    prompt = PROMPT.format(title=title or "unknown", author=f" by {author}" if author else "", lang=lang,
                           accent=" (a native speaker of the book's language, unless the story suggests otherwise)",
                           max_chars=max_chars, text=text[start:start + excerpt_chars])
    reply = llm.complete(prompt, system=SYSTEM, temperature=0.5)
    out = " ".join(reply.replace("```", " ").split())
    out = re.sub(r"^(voice description|description)\s*:\s*", "", out, flags=re.I).strip(" \"'“”")
    if len(out) > max_chars:
        cut = out[:max_chars]
        out = cut[: cut.rfind(". ") + 1] if ". " in cut else cut.rstrip()
    if len(out) < 20 or BAD.search(out):
        raise ValueError("The LLM did not return a usable voice description; try again or write one yourself")
    return out
