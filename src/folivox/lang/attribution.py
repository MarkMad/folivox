"""Language data for reading who is meant by a piece of narration next to speech (pronouns, Russian speech verbs)."""

import re

# (masculine, feminine) pronouns by language; a language with no entry (or an ambiguous pronoun) gives no hint
PRONOUNS = {"en": ({"he", "him", "his"}, {"she", "her", "hers"}),
            "ru": ({"он", "его", "ему"}, {"она", "её", "ее", "ей"}),
            "de": ({"er", "ihn", "ihm"}, set()), "fr": ({"il", "lui"}, {"elle"}), "es": ({"él"}, {"ella"}),
            "it": ({"lui"}, {"lei"})}

# Russian past-tense speech verbs: the ending "а" is feminine ("спросила"), none is masculine ("спросил")
RU_SAID = re.compile(r"\b(сказал|спросил|ответил|воскликнул|прошептал|крикнул|пробормотал|проговорил|добавил|"
                     r"заметил|произн[её]с|закричал|вздохнул|улыбнул|усмехнул|буркнул|рявкнул)(а)?(ся|сь)?\b", re.I)
