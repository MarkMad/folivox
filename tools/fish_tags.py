#!/usr/bin/env python3
"""List expression tags found in the vendors' public pages that ``expression_tags.json`` does not have yet.

    python tools/fish_tags.py

Reads the S2 Pro and Drama 3 model cards (Hugging Face) and Fish Audio's emotion documentation, extracts
``[tag]`` tokens from code and prose, and prints the ones missing from the database. It never edits the file:
add real tags by hand, with their category and the page they came from. Standard library only.
"""

import json
import re
import urllib.request
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "src" / "folivox" / "tts" / "expression_tags.json"
PAGES = {
    "s2card": "https://huggingface.co/fishaudio/s2-pro/raw/main/README.md",
    "d3card": "https://huggingface.co/fishaudio/drama-3/raw/main/README.md",
}


def main() -> None:
    known = {t["tag"] for t in json.loads(DB.read_text(encoding="utf-8"))["tags"]}
    for name, url in PAGES.items():
        text = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "folivox"}), timeout=30).read()
        found = {m.strip().lower() for m in re.findall(r"\[([a-zA-Z][a-zA-Z \-]{1,30})\]", text.decode("utf-8", "replace"))}
        new = sorted(found - known)
        print(f"{name}: {len(found)} bracketed words, {len(new)} not in the database")
        for t in new:
            print(f"   [{t}]")
    print("Also check https://docs.fish.audio/developer-guide/core-features/emotions by hand (it is a web app).")


if __name__ == "__main__":
    main()
