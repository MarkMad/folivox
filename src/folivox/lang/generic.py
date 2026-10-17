"""A language without rules of its own: the text goes to the voice model almost as it is.

Online engines (Fish Audio and others) read numbers, dates and abbreviations of dozens of languages by
themselves, so for a book language outside :data:`folivox.lang.SUPPORTED` nothing is expanded here: only
whitespace, quotes and dashes are cleaned and sentences are split on the terminators of every script.
"""

from __future__ import annotations

import re
import unicodedata

from folivox.lang.base import Language, collapse, punctuation, split_sentences

# ISO 639-1 code → (English name, self-name)
NAMES: dict[str, tuple[str, str]] = {
    "uk": ("Ukrainian", "Українська"), "be": ("Belarusian", "Беларуская"), "pl": ("Polish", "Polski"),
    "cs": ("Czech", "Čeština"), "sk": ("Slovak", "Slovenčina"), "bg": ("Bulgarian", "Български"),
    "sr": ("Serbian", "Српски"), "hr": ("Croatian", "Hrvatski"), "sl": ("Slovenian", "Slovenščina"),
    "pt": ("Portuguese", "Português"), "nl": ("Dutch", "Nederlands"), "sv": ("Swedish", "Svenska"),
    "da": ("Danish", "Dansk"), "no": ("Norwegian", "Norsk"), "nb": ("Norwegian", "Norsk bokmål"),
    "fi": ("Finnish", "Suomi"), "tr": ("Turkish", "Türkçe"), "el": ("Greek", "Ελληνικά"),
    "he": ("Hebrew", "עברית"), "ar": ("Arabic", "العربية"), "hi": ("Hindi", "हिन्दी"), "la": ("Latin", "Latina"),
    "hu": ("Hungarian", "Magyar"), "ro": ("Romanian", "Română"), "lt": ("Lithuanian", "Lietuvių"),
    "lv": ("Latvian", "Latviešu"), "et": ("Estonian", "Eesti"), "id": ("Indonesian", "Bahasa Indonesia"),
    "vi": ("Vietnamese", "Tiếng Việt"), "th": ("Thai", "ไทย"), "fa": ("Persian", "فارسی"),
    "ka": ("Georgian", "ქართული"), "hy": ("Armenian", "Հայերեն"), "ur": ("Urdu", "اردو"),
    "bn": ("Bengali", "বাংলা"), "ta": ("Tamil", "தமிழ்"), "te": ("Telugu", "తెలుగు"), "mr": ("Marathi", "मराठी"),
    "gu": ("Gujarati", "ગુજરાતી"), "ms": ("Malay", "Bahasa Melayu"), "sw": ("Swahili", "Kiswahili"),
    "ca": ("Catalan", "Català"), "is": ("Icelandic", "Íslenska"), "mk": ("Macedonian", "Македонски"),
    "sq": ("Albanian", "Shqip"), "af": ("Afrikaans", "Afrikaans"), "az": ("Azerbaijani", "Azərbaycanca"),
    "kk": ("Kazakh", "Қазақша"), "uz": ("Uzbek", "Oʻzbekcha"), "mn": ("Mongolian", "Монгол"),
    "ne": ("Nepali", "नेपाली"), "pa": ("Punjabi", "ਪੰਜਾਬੀ"), "kn": ("Kannada", "ಕನ್ನಡ"),
    "ml": ("Malayalam", "മലയാളം"), "si": ("Sinhala", "සිංහල"), "km": ("Khmer", "ខ្មែរ"), "lo": ("Lao", "ລາວ"),
    "my": ("Burmese", "မြန်မာ"), "am": ("Amharic", "አማርኛ"), "tl": ("Tagalog", "Tagalog"),
    "eu": ("Basque", "Euskara"), "gl": ("Galician", "Galego"), "cy": ("Welsh", "Cymraeg"),
    "ga": ("Irish", "Gaeilge"), "mt": ("Maltese", "Malti"), "lb": ("Luxembourgish", "Lëtzebuergesch"),
    "bs": ("Bosnian", "Bosanski"), "yi": ("Yiddish", "ייִדיש"), "ps": ("Pashto", "پښتو"),
}

# Terminators of every script: . ! ? … (Latin, Greek question mark handled below), 。！？ (CJK),
# ؟ ۔ (Arabic, Urdu), । ॥ (Indic), ։ (Armenian), ። (Ethiopic)
_END = r"[.!?…。！？؟۔।॥։።]+[\"'»”’)\]」』]*(?:\s+(?=[^\s])|$)"
_GREEK_Q = r"(?<=[Ͱ-Ͽ]);\s+(?=[^\s])"
_NO_PUNCTUATION = frozenset({"th", "lo", "km", "my"})  # clauses are separated by spaces, not by marks


class GenericLanguage(Language):
    def __init__(self, code: str):
        self.code = code
        self.name, self.native = NAMES.get(code, (code.upper(), code))
        self.cps = (3.0, 30.0)  # no measured range: QA only rejects extreme speaking rates

    def normalize(self, text: str) -> str:
        return collapse(punctuation(text))

    def numbers(self, text: str) -> str:
        return text

    def sentences(self, text: str) -> list[str]:
        if self.code in _NO_PUNCTUATION:
            out: list[str] = []
            for para in re.split(r"\n+", text):
                out += [p for p in re.split(r"\s+", para.strip()) if p]
            return out
        end = f"(?:{_END})|(?:{_GREEK_Q})" if self.code == "el" else _END
        return split_sentences(text, self.abbreviations, end=end)

    def dialogue(self, text: str) -> str:
        return re.sub(r"^\s*[—―–-]\s*", "", text)

    def canonical(self, text: str) -> str:
        text = unicodedata.normalize("NFKC", text).lower()
        text = "".join(c if (c.isalnum() or c.isspace()) else " " for c in text)
        return " ".join(text.split())

