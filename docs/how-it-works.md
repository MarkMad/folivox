# How it works

1. **Read** — a reader per format produces a common `Book` model: metadata, cover, nested sections,
   typed blocks (paragraph, epigraph, poem, quote…). Footnotes are skipped; PDF headers, footers and
   page numbers are removed and hyphenation is undone.
2. **Normalise** — a language module turns numbers and abbreviations into words (and restores ё
   for Russian), splits sentences ([razdel](https://github.com/natasha/razdel) for Russian, a
   punctuation splitter elsewhere, including `。！？` for Chinese and Japanese) and packs them into
   fragments.
3. **Synthesise** — CosyVoice 3 clones the voice zero-shot. Each accepted take is stored in the
   work dir and recorded in an SQLite journal.
4. **Check** — Whisper transcribes the take; character error rate and speaking rate decide whether
   to retake.
5. **Assemble** — fragments are joined with structural pauses (sentence < paragraph < heading <
   chapter), loudness-normalised (EBU R128, −18 LUFS) and encoded to AAC in an `.m4b` with chapters.
