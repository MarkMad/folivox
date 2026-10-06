"""Russian: the most polished language (case agreement for numbers, ё restoration, razdel)."""

from __future__ import annotations

import re

from folivox.lang import Language, register


class Russian(Language):
    code, name, native = "ru", "Russian", "Русский"
    cps = (7.0, 23.0)  # measured: normal narration 15–18.5, dropped sentence tails 21–24
    part_words = ("часть", "книга", "том", "раздел")
    chapter_words = ("глава",)
    standalone_words = ("пролог", "эпилог", "предисловие", "послесловие", "вступление", "введение",
                        "заключение", "от автора")
    hallucinations = (
        r"продолжение следует\W*",
        r"субтитры (?:сделал|делал|создавал|подготовил)\w*[^.!?]*[.!?]?",
        r"редактор субтитров[^.!?]*[.!?]?",
        r"корректор [а-яё.]+\s*[а-яё]+\W*",
        r"спасибо за (?:просмотр|внимание)\W*",
        r"подписывайтесь на (?:наш )?канал\W*",
        r"ставьте лайки?\W*",
        r"до (?:новых )?встречи?\W*",
    )

    def normalize(self, text: str) -> str:
        from folivox.text.normalize import normalize

        return normalize(text)

    def numbers(self, text: str) -> str:
        return self.normalize(text)

    def sentences(self, text: str) -> list[str]:
        from razdel import sentenize

        return [s.text.strip() for s in sentenize(text) if s.text.strip()]

    def is_continuation(self, sentence: str) -> bool:
        return bool(re.match(r"^[\s—–-]*[а-яё]", sentence))

    def stress(self, text: str, mode: str) -> str:
        from folivox.text import stress

        return stress.apply(text, mode)

    def canonical(self, text: str) -> str:
        # Whisper writes times as «7.30»; make them look like «7:30» before normalising
        text = re.sub(r"\b(\d{1,2})\.(\d{2})\b(?!\.\d)", r"\1:\2", text)
        text = self.normalize(text).lower().replace("ё", "е").replace("́", "")
        text = re.sub(r"[^0-9a-zа-я ]+", " ", text.replace("-", " "))
        return " ".join(text.split())


register(Russian())
