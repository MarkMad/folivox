#!/usr/bin/env python3
"""Check whether the pinned audio.cpp release, packages and Drama 3 port have moved on (run it every month or two).

    python tools/native_catalog.py watch

audio.cpp is a young project: new releases, new GGUF packages, speed changes and the Drama 3 port (today only in an
unofficial fork) can appear at any time. This script only reads (GitHub and Hugging Face APIs) and prints what is new
and which of our measurements are older than the recheck period; it changes nothing. After a change worth adopting,
update ``src/folivox/tts/native_catalog.json`` (pins, sizes, sha256) and ``catalog.json``, run
``folivox bench`` on the new release and record the numbers in ``measurements`` / ``tested_on``.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

CAT = Path(__file__).resolve().parents[1] / "src" / "folivox" / "tts" / "native_catalog.json"
FISH = Path(__file__).resolve().parents[1] / "src" / "folivox" / "tts" / "catalog.json"


def get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "folivox-native-catalog"})
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 (fixed https URLs)
        return json.loads(r.read())


def watch() -> int:
    cat = json.loads(CAT.read_text(encoding="utf-8"))
    src = cat["sources"]
    notes: list[str] = []
    up = src["upstream"]["repo"].removeprefix("https://github.com/")
    try:
        latest = get(f"https://api.github.com/repos/{up}/releases/latest")
        if latest["tag_name"] != cat["release"]:
            notes.append(f"NEW audio.cpp release {latest['tag_name']} (pinned {cat['release']}, published "
                         f"{latest['published_at'][:10]}): {latest['html_url']}")
        else:
            notes.append(f"audio.cpp release is still {cat['release']}")
        names = {a["name"] for a in latest["assets"]}
        for b in cat["binaries"]:
            for a in b["assets"]:
                if a["name"].replace(cat["release"], latest["tag_name"]) not in names:
                    notes.append(f"  asset missing in the latest release: {a['name']}")
    except (urllib.error.URLError, OSError, KeyError) as e:
        notes.append(f"could not read the releases ({e})")
    try:
        tree = get(f"https://api.github.com/repos/{up}/git/trees/main?recursive=1")["tree"]
        paths = {t["path"] for t in tree}
        if "docs/models/fish_drama3.md" in paths:
            notes.append("Drama 3 is now in upstream audio.cpp main: switch the drama3 builds to the release binaries "
                         "and drop the unofficial fork (sources.drama3_fork)")
        else:
            notes.append("Drama 3 is still not in upstream audio.cpp main (fork only)")
    except (urllib.error.URLError, OSError, KeyError) as e:
        notes.append(f"could not read the upstream tree ({e})")
    fk = src["drama3_fork"]
    try:
        repo = fk["repo"].removeprefix("https://github.com/").removesuffix(".git")
        head = get(f"https://api.github.com/repos/{repo}/branches/{fk['branch']}")["commit"]["sha"]
        notes.append("fork branch head " + ("is the pinned commit" if head == fk["commit"] else
                                            f"moved: {head[:8]} (pinned {fk['commit'][:8]})"))
    except (urllib.error.URLError, OSError, KeyError) as e:
        notes.append(f"could not read the fork branch ({e})")
    for key, w in (("CosyVoice 3", cat["weights"]["cosyvoice3"]),):
        try:
            sha = get(f"https://huggingface.co/api/models/{w['repo']}")["sha"]
            notes.append(f"{key} GGUF repo " + ("unchanged" if sha == w["revision"] else
                                               f"changed: {sha[:8]} (pinned {w['revision'][:8]})"))
        except (urllib.error.URLError, OSError, KeyError) as e:
            notes.append(f"could not read {w['repo']} ({e})")
    for b in json.loads(FISH.read_text(encoding="utf-8"))["builds"]:
        if b["backend"] != "native":
            continue
        try:
            sha = get(f"https://huggingface.co/api/models/{b['repo']}")["sha"]
            if sha != b["revision"]:
                notes.append(f"{b['id']}: repo {b['repo']} changed ({sha[:8]}, pinned {b['revision'][:8]})")
        except (urllib.error.URLError, OSError, KeyError) as e:
            notes.append(f"could not read {b['repo']} ({e})")
    after = int(cat.get("recheck", {}).get("after_days", 60))
    for m in cat.get("measurements", []):
        age = (dt.date.today() - dt.date.fromisoformat(m["date"])).days
        notes.append(f"measurement {m['engine']} on {m['platform']} is {age} days old"
                     + (" -> MEASURE AGAIN (folivox bench --devices native,cpu)" if age > after else ""))
    print("\n".join(notes))
    return 0


if __name__ == "__main__":
    if sys.argv[1:] != ["watch"]:
        print(__doc__)
        sys.exit(2)
    sys.exit(watch())
