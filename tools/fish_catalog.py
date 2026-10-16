#!/usr/bin/env python3
"""Maintain ``src/folivox/tts/catalog.json`` (the Fish Audio builds Folivox offers).

    python tools/fish_catalog.py pin REPO [--revision SHA]   # revision + file sizes/sha256 of a build, as JSON
    python tools/fish_catalog.py watch [--json]               # what is new on Hugging Face compared with the catalog

``watch`` is meant to run now and then (monthly is enough; a scheduled job or by hand). It never downloads
weights and never changes the catalog: a build enters the catalog only after it was run on the standard
test fragment (real-time factor, peak memory, CER) and someone added the entry with those numbers.
It reads only public Hugging Face metadata. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://huggingface.co/api"
CATALOG = Path(__file__).resolve().parents[1] / "src" / "folivox" / "tts" / "catalog.json"
# Upstream models whose quantised conversions are worth a look, and where new releases show up.
BASES = ("fishaudio/drama-3", "fishaudio/s2-pro")
RELEASE_ORGS = ("fishaudio",)
TRUSTED_ORGS = ("mlx-community", "fishaudio")


def get(path: str, **params) -> object:
    url = f"{API}/{path}" + (("?" + urllib.parse.urlencode(params)) if params else "")
    req = urllib.request.Request(url, headers={"User-Agent": "folivox-catalog-watch"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def pin(repo: str, revision: str | None = None) -> dict:
    """The facts a catalog entry needs: the exact revision and every file with size and (for large files) sha256."""
    info = get(f"models/{repo}" + (f"/revision/{revision}" if revision else ""), blobs="true")
    files = []
    for s in info["siblings"]:
        lfs = s.get("lfs") or {}
        files.append({"path": s["rfilename"], "size": s.get("size") or 0, "sha256": lfs.get("sha256")})
    return {"repo": repo, "revision": info["sha"], "size_bytes": sum(f["size"] for f in files), "files": files,
            "tags": info.get("tags", []), "last_modified": info.get("lastModified")}


def known_repos() -> set[str]:
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    return {b["repo"] for b in data["builds"]}


def watch() -> dict:
    """New quantisations of the Fish models and new Fish releases that the catalog does not list yet."""
    known = known_repos()
    found: dict[str, dict] = {}
    for base in BASES:
        rows = get("models", filter=f"base_model:quantized:{base}", limit=100, full="false")
        for m in rows:  # type: ignore[union-attr]
            repo = m["id"]
            if repo in known or repo in found:
                continue
            found[repo] = {"repo": repo, "base": base, "trusted_org": repo.split("/")[0] in TRUSTED_ORGS,
                           "downloads": m.get("downloads"), "last_modified": m.get("lastModified"),
                           "tags": [t for t in m.get("tags", []) if t in ("mlx", "gguf", "safetensors", "4-bit",
                                                                          "8-bit", "3-bit", "fp8", "int4")]}
    releases = []
    for org in RELEASE_ORGS:
        for m in get("models", author=org, sort="createdAt", direction="-1", limit=20):  # type: ignore[union-attr]
            if m["id"] not in known and m["id"] not in found and "text-to-speech" in m.get("tags", []) \
                    and m["id"] not in BASES:
                releases.append({"repo": m["id"], "created": m.get("createdAt"), "tags": m.get("tags", [])[:8]})
    return {"quantisations": sorted(found.values(), key=lambda x: x["last_modified"] or "", reverse=True),
            "new_fish_models": releases}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pin")
    p.add_argument("repo")
    p.add_argument("--revision")
    w = sub.add_parser("watch")
    w.add_argument("--json", action="store_true")
    args = ap.parse_args()
    if args.cmd == "pin":
        print(json.dumps(pin(args.repo, args.revision), indent=1))
        return 0
    res = watch()
    if args.json:
        print(json.dumps(res, indent=1))
        return 0
    print("Quantisations not in the catalog:")
    for q in res["quantisations"] or [None]:
        if q is None:
            print("  (none)")
            continue
        print(f"  {q['repo']}  base={q['base']}  trusted_org={'yes' if q['trusted_org'] else 'NO'}  "
              f"{', '.join(q['tags'])}  updated {q['last_modified']}")
    print("\nNew Fish text-to-speech models:")
    for r in res["new_fish_models"] or [None]:
        print("  (none)" if r is None else f"  {r['repo']}  created {r['created']}")
    print("\nA build enters the catalog only after a run on the standard test fragment: "
          "`python tools/fish_catalog.py pin REPO`, test, then add the entry with the measured numbers.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
