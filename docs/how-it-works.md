# How it works

1. **Read** — a reader per format produces a common `Book` model: metadata, cover, nested sections,
   typed blocks (paragraph, epigraph, poem, quote…). Footnotes are skipped; PDF headers, footers and
   page numbers are removed and hyphenation is undone.
2. **Normalise** — a language module turns numbers and abbreviations into words (and restores ё
   for Russian), splits sentences ([razdel](https://github.com/natasha/razdel) for Russian, a
   punctuation splitter elsewhere, including `。！？` for Chinese and Japanese) and packs them into
   fragments.
3. **Synthesise** — CosyVoice 3 clones the voice zero-shot (or an optional Fish Audio engine, which runs
   in its own worker process and Python environment: [Fish Audio engines](fish-engines.md)). Each accepted
   take is stored in the work dir and recorded in an SQLite journal; its key hashes the text, the voice and
   the synthesis settings (engine, build and revision, plus speaker and expression tags when used), so a
   changed engine or build never reuses old audio.
4. **Check** — Whisper transcribes the take; character error rate and speaking rate decide whether
   to retake.
5. **Assemble** — fragments are joined with structural pauses (sentence < paragraph < heading <
   chapter), loudness-normalised (EBU R128, −18 LUFS) and encoded to AAC in an `.m4b` with chapters.

## What the normaliser reads out, per language

Every language gets the same pipeline (abbreviations → roman numerals → dates → times → money → phone
numbers → units → ordinals → gender agreement → symbols → plain numbers); the data and the agreement
rules differ.

| | Roman numerals | Dates / times | Money, units | Agreement and other |
|---|---|---|---|---|
| ru | yes | yes | yes | cases, `ё`, stress marks |
| en | `Henry the eighth`, `Chapter four` | `July fourth`, `seven oh five` | `$5.50` → five dollars fifty cents | `Mr.` → Mister |
| de | `Ludwig der Vierzehnte`, `XVII. Jahrhundert` | `am dritten Mai`, `3.5.2020`, `7:30 Uhr` | `5,50 €`, units | `ein Mann` / `eine Frau` |
| fr | `Louis quatorze`, `XXe siècle` | `1er mai`, `7h30` | `5,50 €`, units | `une fille`, `vingt et une filles` |
| es | `Felipe segundo`, `siglo diecinueve` | `1.º de mayo`, `7:30` | `5,50 €`, units | `veintiuna mujeres`, `doscientas casas` |
| it | `Luigi quattordicesimo`, `XIX secolo` | `1º maggio`, `7:30` | `5,50 €`, units | `un'amica`, `uno zaino`, `3ª` |
| zh | | `7:30`, `2024年` digit by digit | `¥5.5`, units | `两个` instead of `二个` |
| ja | | `7:30` → `七時三十分` | `$5`, `¥500`, units | |
| ko | | `7:30`, months `유월`/`시월` | `₩5,000`, units | native counters: `세 명`, `두 시간`, `스무 살` |

Not covered yet: Japanese kanji readings (needs a morphological analyser such as `pyopenjtalk`),
heteronyms in English, and noun gender in French/German beyond common words and endings.
