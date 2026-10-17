# Studio languages

The web studio (`folivox ui`) has **49 interface languages**. The language menu is in the top-right corner. The first
visit follows the browser language, the choice is remembered in `localStorage` (`folivox.lang`) and applies without
a reload. Only the browser UI is translated: the command line, logs, Python error messages, docs and code stay
English, and so do texts that come from the backend (pipeline warnings and errors, provider descriptions, price
notes).

Interface languages are independent of **book languages**: a book is read in one of nine (Russian, English, German,
French, Spanish, Italian, Chinese, Japanese, Korean), the menu may be in any of the 49.

| Group | Languages |
|---|---|
| Book languages (also in the menu) | English `en`, Russian `ru`, German `de`, French `fr`, Spanish `es`, Italian `it`, Chinese `zh`, Japanese `ja`, Korean `ko` |
| Western and Southern Europe | Portuguese `pt`, Dutch `nl`, Catalan `ca`, Greek `el`, Albanian `sq` |
| Northern Europe | Swedish `sv`, Danish `da`, Norwegian Bokmål `nb`, Finnish `fi`, Icelandic `is`, Estonian `et`, Latvian `lv`, Lithuanian `lt` |
| Central and Eastern Europe | Polish `pl`, Czech `cs`, Slovak `sk`, Hungarian `hu`, Romanian `ro`, Ukrainian `uk`, Bulgarian `bg`, Serbian (Cyrillic) `sr`, Croatian `hr`, Slovenian `sl`, Macedonian `mk` |
| Middle East, right to left | Arabic `ar`, Hebrew `he`, Persian `fa`, Urdu `ur` |
| Middle East and Central Asia, left to right | Turkish `tr` |
| South and Southeast Asia, Africa | Hindi `hi`, Bengali `bn`, Marathi `mr`, Telugu `te`, Tamil `ta`, Gujarati `gu`, Indonesian `id`, Malay `ms`, Vietnamese `vi`, Thai `th`, Swahili `sw` |

## Right to left

Arabic, Hebrew, Persian and Urdu are right to left: `applyI18n` sets `<html dir="rtl">` from `RTL_LANGS` in
`index.html`, and the stylesheet uses only logical properties (`margin-inline-start`, `text-align: start`,
`inset-inline-end`...), so the page mirrors by itself. Book text, pronunciation rules, `code` and `kbd` stay left to
right. Numbers use Latin digits in every language. Never write `margin-left`, `padding-right`, `text-align: left`
and the like in the stylesheet (`tests/test_ui_i18n.py` fails on it). The play buttons are not mirrored, as in
every media player.

## Checking the catalogs

`python3 scripts/check_i18n.py` (part of `scripts/check.sh`, so of the pre-push hook and CI) reports missing keys,
changed placeholders, strings left identical to English, unused keys and keys the page asks for that no catalog has.
Intentional identical strings (units, product names, words spelled the same) go to `scripts/i18n-allowlist.json` as
`"key@lang": "why"`.

## How strings are organised

* `src/folivox/ui/static/i18n/<code>.json`: one flat `{"key": "text"}` file per language. `en.json` is the source
  of the keys and the fallback: a missing key in another language shows the English text, never a blank.
* `static/index.html`:
  * static markup carries `data-i18n="key"` (text), `data-i18n-html="key"` (text with `<b>`, `<code>`, `<small>`)
    and `data-i18n-attr="placeholder:key;title:key2"` (attributes); the English text stays in the HTML as well;
  * strings built in JavaScript use `t("key", {name: value})`; placeholders are written `{name}`;
  * `refreshUi()` redraws what JavaScript built (chapters, voices, engine cards, settings) after a switch.
* The catalogs are served by `/i18n/<code>.json` in `ui/app.py` (the Host check applies; the files hold no secrets).
* Durations use the unit keys `u.h`, `u.min`, `u.s`; numbers use `Intl` for non-English languages. Phrases avoid
  plurals where possible ("attempts: {n}").

## Fix a translation

Edit the text in `i18n/<code>.json`. Keep every `{placeholder}` and every HTML tag exactly as in `en.json`; the
tests check this. Keep the terms consistent within a language (fragment, chapter, take, preview, voice, engine,
spending cap). Do not translate product and provider names, file extensions or `folivox` commands.

## Add a language

1. Copy `en.json` to `<code>.json` and translate the values (a book language is not needed for an interface language).
2. Add `["<code>", "<native name>"]` to `UI_LANGS` in `index.html` (and the code to `RTL_LANGS` if the script is
   right to left), and the same pair to `NATIVE` in `tests/test_ui_i18n.py`; add the language to the table above.
3. Add the intentional identical strings to `scripts/i18n-allowlist.json`.
4. Look at the page in the new language at desktop and phone width (long words in tiles, chips and buttons).
5. Run `uv run pytest tests/test_ui_i18n.py -q`.

## Add or change a UI string

Add the key to `en.json` and use it in `index.html`, then add the translations (a language that lacks the key shows
English; to allow that for a while, list the key in `ALLOW_MISSING` in `tests/test_ui_i18n.py`). The tests fail if
a key used by the page is missing from `en.json`, if a catalog has other keys than English, or if placeholders or
tags differ.
