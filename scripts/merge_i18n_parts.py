#!/usr/bin/env python3
"""Merge translated parts into one catalog: merge_i18n_parts.py <code> <part.json>...

Keeps the key order of en.json, refuses missing keys, and writes src/folivox/ui/static/i18n/<code>.json
in the same format as the other catalogs (one space indent, UTF-8, no ASCII escaping).
"""
import json
import sys
from pathlib import Path

I18N = Path(__file__).resolve().parent.parent / "src/folivox/ui/static/i18n"
code, parts = sys.argv[1], sys.argv[2:]
en = json.loads((I18N / "en.json").read_text("utf-8"))
got: dict[str, str] = {}
for part in parts:
    got.update(json.loads(Path(part).read_text("utf-8")))
missing = [k for k in en if k not in got]
extra = [k for k in got if k not in en]
if missing or extra:
    sys.exit(f"missing {len(missing)}: {missing[:10]}\nextra {len(extra)}: {extra[:10]}")
(I18N / f"{code}.json").write_text(json.dumps({k: got[k] for k in en}, ensure_ascii=False, indent=1) + "\n", "utf-8")
print(f"wrote {code}.json: {len(en)} keys")
