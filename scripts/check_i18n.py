#!/usr/bin/env python3
"""Check the web studio's UI string packs (`src/folivox/ui/static/i18n/*.json`).

Stdlib only, exit code 1 on any finding, so the pre-push hook can block a push.

  1. coverage      a key present in one language and missing in another (both ways);
  2. empty         an empty value;
  3. placeholders  `{name}` sets must match the source language, otherwise a translation
                   silently drops the number or the name it should show;
  4. copy          a value identical to English is usually a forgotten translation;
                   intentional ones (units, product names, "ID") go to
                   `scripts/i18n-allowlist.json` as {"key": "why"} or {"key@lang": "why"};
  5. nowhere       the page asks for a key that no pack has: the user would see the raw key;
  6. orphan        a key the page never uses: a string nobody shows is a string nobody
                   notices going stale, and it gets translated nine times for nothing.

    python3 scripts/check_i18n.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
I18N = ROOT / "src/folivox/ui/static/i18n"
SOURCES = [ROOT / "src/folivox/ui/static/index.html"]
ALLOWLIST = ROOT / "scripts/i18n-allowlist.json"
SOURCE_LANG = "en"

# Key families built in code from a variable ("cover.state." + kind, `mode.${m}.h`) never appear
# literally in the page. They are found by their literal prefix; every key under such a prefix
# counts as used, so the "orphan" check does not guard those families.
DYNAMIC = re.compile(r"""["'`]([\w]+(?:\.[\w]+)*\.)(?:["'`]\s*\+|\$\{)""")

PLACEHOLDER = re.compile(r"\{(\w+)\}")
# t("key"), data-i18n="key", data-i18n-html="key", data-i18n-attr="attr:key;attr:key"
CALL = re.compile(r"""\bt\(\s*(["'])([\w.\-]+)\1""")
ATTR = re.compile(r"""\bdata-i18n(?:-html)?="([\w.\-]+)\"""")
ATTR_MAP = re.compile(r"""\bdata-i18n-attr="([^"]+)\"""")


def load_packs() -> dict[str, dict[str, str]]:
    return {p.stem: json.loads(p.read_text("utf-8")) for p in sorted(I18N.glob("*.json"))}


def used_keys(text: str) -> set[str]:
    keys = {m.group(2) for m in CALL.finditer(text)}
    keys |= {m.group(1) for m in ATTR.finditer(text)}
    for m in ATTR_MAP.finditer(text):
        for pair in m.group(1).split(";"):
            if ":" in pair:
                keys.add(pair.split(":", 1)[1].strip())
    return keys


def main() -> int:
    packs = load_packs()
    source = packs.get(SOURCE_LANG)
    if source is None:
        print(f"x {SOURCE_LANG}.json not found: nothing to compare against")
        return 1
    allow = json.loads(ALLOWLIST.read_text("utf-8")) if ALLOWLIST.exists() else {}

    problems: dict[str, list[str]] = {k: [] for k in ("missing", "extra", "empty", "placeholders", "copy", "nowhere", "orphan", "allowlist")}

    for lang, pack in packs.items():
        for key in source:
            if key not in pack:
                problems["missing"].append(f"{key}  ->  {lang}")
        for key, value in pack.items():
            if key not in source:
                problems["extra"].append(f"{key}  ->  {lang}")
                continue
            if not str(value).strip():
                problems["empty"].append(f"{key}  ->  {lang}")
            mine, theirs = sorted(set(PLACEHOLDER.findall(value))), sorted(set(PLACEHOLDER.findall(source[key])))
            if mine != theirs:
                problems["placeholders"].append(f"{key}  ->  {lang}: {mine} vs {theirs}")
            if lang != SOURCE_LANG and value == source[key] and key not in allow and f"{key}@{lang}" not in allow:
                problems["copy"].append(f"{key}  ->  {lang}")

    text = "\n".join(p.read_text("utf-8") for p in SOURCES if p.exists())
    used = used_keys(text)
    prefixes = tuple(set(DYNAMIC.findall(text)))
    for key in sorted(used - set(source)):
        if not key.endswith("."):  # a bare prefix of a computed key, not a key
            problems["nowhere"].append(key)
    for key in source:
        if key not in used and not key.startswith(prefixes) and f'"{key}"' not in text and f"'{key}'" not in text:
            problems["orphan"].append(key)

    # An allowlist entry that points nowhere, or whose text is no longer a copy, is stale.
    for entry in allow:
        key, _, lang = entry.partition("@")
        if key not in source or (lang and lang not in packs):
            problems["allowlist"].append(f"{entry}: key or language no longer exists")
        elif not any(packs[l].get(key) == source[key] for l in ([lang] if lang else packs) if l != SOURCE_LANG):
            problems["allowlist"].append(f"{entry}: no longer identical to English, remove it")

    labels = {
        "missing": "Missing in a pack (present in English)",
        "extra": "In a pack but not in English",
        "empty": "Empty value",
        "placeholders": "Placeholders differ from English",
        "copy": "Identical to English: probably untranslated (or add to scripts/i18n-allowlist.json with a reason)",
        "nowhere": "Page asks for a key that no pack has: the raw key is shown",
        "orphan": "Key is not used by the page: remove it or wire it up",
        "allowlist": "Stale entry in scripts/i18n-allowlist.json",
    }
    total = sum(len(v) for v in problems.values())
    if not total:
        print(f"ok i18n: {len(source)} keys, languages {', '.join(packs)}: no discrepancies")
        return 0
    print(f"x i18n: {total} findings", file=sys.stderr)
    for kind, items in problems.items():
        if items:
            print(f"\n  {labels[kind]} ({len(items)}):", file=sys.stderr)
            for item in items:
                print(f"    {item}", file=sys.stderr)
    print("", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
