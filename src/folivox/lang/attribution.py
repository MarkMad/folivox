"""Language data for reading who is meant by a piece of narration next to speech (pronouns, Russian speech verbs)."""

import re

# (masculine, feminine) subject pronouns by language: only the subject of "he said" is the speaker ("said Anna to
# him" has a "him" who is not); a language with no entry (or an ambiguous pronoun) gives no hint
PRONOUNS = {"en": ({"he"}, {"she"}), "ru": ({"он"}, {"она"}), "de": ({"er"}, set()), "fr": ({"il"}, {"elle"}),
            "es": ({"él"}, {"ella"}), "it": ({"lui", "egli"}, {"lei", "ella"})}

# Russian past-tense speech verbs: the ending "а" is feminine ("спросила"), none is masculine ("спросил")
RU_SAID = re.compile(r"\b(сказал|спросил|ответил|воскликнул|прошептал|крикнул|пробормотал|проговорил|добавил|"
                     r"заметил|произн[её]сл?|закричал|вздохнул|улыбнул|усмехнул|буркнул|рявкнул)(а)?(ся|сь)?\b", re.I)
