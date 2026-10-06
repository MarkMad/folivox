from __future__ import annotations

import re

from num2words import num2words

from folivox.lang import CJKLanguage, register


class Japanese(CJKLanguage):
    code, name, native = "ja", "Japanese", "日本語"
    chapter_label, intro_label = "第{n}章", "序章"
    cps = (3.0, 12.0)
    hallucinations = (r"ご視聴ありがとうございました\W*", r"(?:チャンネル登録|字幕)[^。！？]*[。！？]?")

    def numbers(self, text: str) -> str:
        return re.sub(r"\d+(?:\.\d+)?", lambda m: self.number(m.group(0)), text)

    def number(self, s: str) -> str:
        try:
            return num2words(float(s) if "." in s else int(s), lang="ja")
        except (NotImplementedError, ValueError):
            return s


register(Japanese())
