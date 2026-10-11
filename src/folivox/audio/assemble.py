"""Assemble chunk audio into chapters and the final audiobook (m4b with chapters, or mp3s)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from folivox.audio import load

LOUDNORM = "loudnorm=I=-18:TP=-1.5:LRA=11"


class FFmpegMissing(RuntimeError):
    pass


# Any image (PNG, WebP, a 6000 px scan…) becomes a JPEG of at most 1600 px wide: what players expect, and small.
COVER_ARGS = ["-c:v", "mjpeg", "-vf", "scale='min(1600,iw)':-2:flags=lanczos,format=yuvj420p", "-q:v", "3",
              "-disposition:v:0", "attached_pic"]


def ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise FFmpegMissing("ffmpeg not found. Install it: macOS — brew install ffmpeg; "
                              "Windows — winget install ffmpeg; Linux — apt install ffmpeg")
    return exe


def run(args: list[str]) -> None:
    proc = subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", *args],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg failed:" + "\n" + proc.stderr.strip())


@dataclass
class ChapterAudio:
    title: str
    path: Path
    duration: float


def build_chapter(parts: list[tuple[Path, float]], out: Path, sample_rate: int, lead_in: float = 0.3) -> float:
    """Concatenate chunk files with the given trailing pauses, loudness-normalise, write FLAC."""
    import soundfile as sf

    pieces = [np.zeros(int(sample_rate * lead_in), np.float32)]
    for path, pause in parts:
        audio, sr = load(path)
        if sr != sample_rate:
            raise ValueError(f"{path}: sample rate {sr} != {sample_rate}")
        pieces += [audio, np.zeros(int(sample_rate * pause), np.float32)]
    audio = np.concatenate(pieces)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "raw.wav"
        sf.write(str(raw), audio, sample_rate, subtype="PCM_16")
        run(["-i", str(raw), "-af", LOUDNORM, "-ar", str(sample_rate), "-ac", "1", "-c:a", "flac",
             str(out.with_suffix(".tmp.flac"))])
    out.with_suffix(".tmp.flac").replace(out)
    return len(audio) / sample_rate


def _concat_path(p: Path) -> str:
    return p.resolve().as_posix().replace("'", "'\\''")


def _escape_meta(s: str) -> str:
    for ch in ("\\", "=", ";", "#", "\n"):
        s = s.replace(ch, "\\" + ch)
    return s


@dataclass
class BookMeta:
    title: str
    author: str = ""
    year: str = ""
    comment: str = ""
    narrator: str = ""
    series: str = ""
    series_part: str = ""
    genre: str = ""


def grouping(meta: BookMeta) -> str:
    """The Grouping tag most audiobook apps read as the series: "Name #3"."""
    return f"{meta.series} #{meta.series_part}".strip() if meta.series and meta.series_part else meta.series


def write_m4b(chapters: list[ChapterAudio], out: Path, meta: BookMeta, cover: bytes | None = None,
              bitrate: str = "64k") -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmpd = Path(tmp)
        lst = tmpd / "list.txt"
        lst.write_text("".join(f"file '{_concat_path(c.path)}'\n" for c in chapters), encoding="utf-8")
        md = [";FFMETADATA1", f"title={_escape_meta(meta.title)}", f"album={_escape_meta(meta.title)}",
              f"artist={_escape_meta(meta.author)}", f"album_artist={_escape_meta(meta.author)}",
              f"genre={_escape_meta(meta.genre or 'Audiobook')}", "encoder=Folivox"]
        if meta.series:
            md.append(f"grouping={_escape_meta(grouping(meta))}")
        if meta.year:
            md.append(f"date={meta.year}")
        if meta.comment:
            md.append(f"comment={_escape_meta(meta.comment[:1000])}")
        if meta.narrator:
            md.append(f"composer={_escape_meta(meta.narrator)}")
        t = 0
        for c in chapters:
            start, t = t, t + int(round(c.duration * 1000))
            md += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={start}", f"END={t}", f"title={_escape_meta(c.title)}"]
        (tmpd / "meta.txt").write_text("\n".join(md) + "\n", encoding="utf-8")

        args = ["-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(tmpd / "meta.txt")]
        maps = ["-map", "0:a", "-map_metadata", "1", "-map_chapters", "1"]
        if cover:
            cov = tmpd / "cover.img"
            cov.write_bytes(cover)
            args += ["-i", str(cov)]
            maps += ["-map", "2:v", *COVER_ARGS]
        tmp_out = tmpd / "book.m4b"
        run([*args, *maps, "-c:a", "aac", "-b:a", bitrate, "-ac", "1", "-movflags", "+faststart",
             "-f", "mp4", str(tmp_out)])
        shutil.move(str(tmp_out), out)


def write_mp3s(chapters: list[ChapterAudio], out_dir: Path, meta: BookMeta, cover: bytes | None = None,
               bitrate: str = "96k") -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    width = len(str(len(chapters)))
    with tempfile.TemporaryDirectory() as tmp:
        cov = None
        if cover:
            cov = Path(tmp) / "cover.img"
            cov.write_bytes(cover)
        for i, c in enumerate(chapters, 1):
            safe = "".join(ch for ch in c.title if ch not in '<>:"/\\|?*').strip()[:80] or f"{i:03d}"
            p = out_dir / f"{i:0{width}d} - {safe}.mp3"
            args = ["-i", str(c.path)]
            maps = ["-map", "0:a"]
            if cov:
                args += ["-i", str(cov)]
                maps += ["-map", "1:v", *COVER_ARGS]
            run([*args, *maps, "-c:a", "libmp3lame", "-b:a", bitrate, "-ac", "1", "-id3v2_version", "3",
                 "-metadata", f"title={c.title}", "-metadata", f"album={meta.title}",
                 "-metadata", f"artist={meta.author}", "-metadata", f"album_artist={meta.author}",
                 "-metadata", f"track={i}/{len(chapters)}", "-metadata", f"genre={meta.genre or 'Audiobook'}",
                 "-metadata", f"composer={meta.narrator}", "-metadata", f"date={meta.year}",
                 "-metadata", f"comment={meta.comment[:1000]}", "-metadata", f"grouping={grouping(meta)}", str(p)])
            paths.append(p)
    return paths
