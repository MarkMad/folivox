"""Reuse weights that are already on this computer instead of downloading them again.

Places looked at: the Hugging Face cache (``HF_HUB_CACHE``, ``HF_HOME``, ``~/.cache/huggingface``), LM Studio
(``~/.lmstudio/models``) and the other Folivox builds under the engines root. A file is a candidate when its path
and size equal the catalog entry; it is used only after its sha256 matches the catalog too. It is hard-linked when
both folders are on one volume, otherwise copied (never a symlink: the owner of the source may delete it).
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from pathlib import Path

from folivox.tts import builds
from folivox.tts.builds import Build

Progress = Callable[[str, int, int], None]


def hf_cache_roots() -> list[Path]:
    roots = []
    if os.environ.get("HF_HUB_CACHE"):
        roots.append(Path(os.environ["HF_HUB_CACHE"]).expanduser())
    if os.environ.get("HF_HOME"):
        roots.append(Path(os.environ["HF_HOME"]).expanduser() / "hub")
    if os.environ.get("XDG_CACHE_HOME"):  # huggingface_hub's default HF_HOME follows it
        roots.append(Path(os.environ["XDG_CACHE_HOME"]).expanduser() / "huggingface" / "hub")
    roots.append(Path.home() / ".cache" / "huggingface" / "hub")
    return roots


def lmstudio_roots() -> list[Path]:
    return [Path.home() / ".lmstudio" / "models"]


def source_dirs(b: Build) -> list[Path]:
    """Folders that may hold this build's files laid out like the repository."""
    org, _, name = b.repo.partition("/")
    out: list[Path] = []
    for root in hf_cache_roots():
        snaps = root / f"models--{org}--{name}" / "snapshots"
        try:
            if snaps.is_dir():
                out += sorted((p for p in snaps.iterdir() if p.is_dir()), key=lambda p: -p.stat().st_mtime)
        except OSError:  # unreadable cache, or a snapshot removed while we look
            continue
    for root in lmstudio_roots():
        out += [root / org / name]
    for other in builds.load().builds:
        if other.id != b.id:
            out.append(builds.weights_dir(other))
    return [d for d in out if d.is_dir()]


def _candidate(dirs: list[Path], f: dict) -> list[Path]:
    found = []
    for d in dirs:
        p = d / f["path"]
        try:
            if p.is_file() and p.stat().st_size == f["size"]:
                found.append(p)
        except OSError:
            continue
    return found


def find(b: Build, dirs: list[Path] | None = None) -> dict[str, list[Path]]:
    """Cheap pass: files with a pinned sha256 that exist elsewhere under the same path and size."""
    dirs = source_dirs(b) if dirs is None else dirs
    wd = builds.weights_dir(b)
    out = {}
    for f in b.files:
        if not f.get("sha256"):
            continue  # nothing to verify against: download these (they are small)
        cands = [p for p in _candidate(dirs, f) if not _same_file(p, wd / f["path"])]
        if cands:
            out[f["path"]] = cands
    return out


def _same_file(a: Path, b: Path) -> bool:
    try:
        return b.exists() and os.path.samefile(a, b)
    except OSError:
        return False


def _place(src: Path, dst: Path) -> str:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".reuse")
    tmp.unlink(missing_ok=True)
    try:
        os.link(src.resolve(), tmp)
        kind = "linked"
    except OSError:  # another volume, or a file system without hard links
        try:
            shutil.copyfile(src, tmp)
        except OSError:
            tmp.unlink(missing_ok=True)  # do not leave a half copy of a multi-GB file behind
            raise
        kind = "copied"
    os.replace(tmp, dst)
    return kind


def adopt(b: Build, hook: Progress | None = None, dirs: list[Path] | None = None) -> dict[str, str]:
    """Verify and put in place every file that can be reused. Returns {path: "linked" | "copied"}."""
    from folivox.tts.fish_setup import sha256_file

    wd = builds.weights_dir(b)
    wanted = {f["path"]: f for f in b.files}
    done: dict[str, str] = {}
    cands = find(b, dirs)
    total = sum(wanted[n]["size"] for n in cands)
    seen = 0
    for name, paths in cands.items():
        f = wanted[name]
        dst = wd / name
        try:
            if dst.is_file() and dst.stat().st_size == f["size"] and sha256_file(dst) == f["sha256"]:
                seen += f["size"]
                continue  # already here and right
        except OSError:
            pass
        for src in paths:
            base = seen

            def tick(n: int, base=base) -> None:
                nonlocal seen
                seen += n
                if hook:
                    hook("Checking files found on this computer", seen, total)

            try:
                ok = sha256_file(src, tick) == f["sha256"]
            except OSError:
                ok = False
            if ok:
                try:
                    done[name] = _place(src, dst)
                    break
                except OSError:
                    continue
            seen = base + f["size"]  # keep the bar monotonic after a mismatch
    return done


def found_bytes(b: Build, dirs: list[Path] | None = None) -> int:
    sizes = {f["path"]: f["size"] for f in b.files}
    return sum(sizes[n] for n in find(b, dirs))
