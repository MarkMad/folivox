from __future__ import annotations

import re

from folivox.lang import CJKLanguage, register


class Korean(CJKLanguage):
    code, name, native = "ko", "Korean", "한국어"
    cps = (3.0, 12.0)
    chapter_words = ()
    hallucinations = (r"시청해\s*주셔서 감사합니다\W*", r"구독과 좋아요[^.!?]*[.!?]?")

    def sentences(self, text: str) -> list[str]:  # Korean uses spaces and Western punctuation
        parts = re.split(r"(?<=[.!?…。！？])\s+", text)
        return [p.strip() for p in parts if p.strip()]

    def numbers(self, text: str) -> str:
        return re.sub(r"(?<![\w.,])\d+(?:\.\d+)?", lambda m: self.number(m.group(0)), text)


register(Korean())
