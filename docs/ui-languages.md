# Studio languages

The web studio (`folivox ui`) speaks English, Russian, Spanish, German, French, Italian, Chinese, Japanese and
Korean: the same languages Folivox can generate books in. The language menu is in the top-right corner. The first
visit follows the browser language, the choice is remembered in `localStorage` (`folivox.lang`) and applies without
a reload. Only the browser UI is translated: the command line, logs, Python error messages, docs and code stay
English, and so do texts that come from the backend (pipeline warnings and errors, provider descriptions, price
notes).

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

1. Add the book language first (`src/folivox/lang/`), if it does not exist.
2. Copy `en.json` to `<code>.json` and translate the values.
3. Add `["<code>", "<native name>"]` to `UI_LANGS` in `index.html`, and the same pair to `NATIVE` in
   `tests/test_ui_i18n.py`.
4. Look at the page in the new language at desktop and phone width (long words in tiles, chips and buttons).
5. Run `uv run pytest tests/test_ui_i18n.py -q`.

## Add or change a UI string

Add the key to `en.json` and use it in `index.html`, then add the translations (a language that lacks the key shows
English; to allow that for a while, list the key in `ALLOW_MISSING` in `tests/test_ui_i18n.py`). The tests fail if
a key used by the page is missing from `en.json`, if a catalog has other keys than English, or if placeholders or
tags differ.
