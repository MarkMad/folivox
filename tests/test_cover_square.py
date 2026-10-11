"""A non-square cover is centre-cropped to a square when the audiobook is written."""
import shutil
import subprocess

import pytest

from folivox.audio.assemble import BookMeta, ChapterAudio, write_m4b

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="needs ffmpeg")


def _run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def test_tall_cover_becomes_square(tmp_path):
    img, snd = tmp_path / "c.png", tmp_path / "c.flac"
    _run("ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=s=300x600", "-frames:v", "1", str(img))
    _run("ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", "1", str(snd))
    out = tmp_path / "b.m4b"
    write_m4b([ChapterAudio("c", snd, 1.0)], out, BookMeta("t", "a", None, "", "", "", "", ""), img.read_bytes(), "64k")
    size = _run("ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=width,height",
                "-of", "csv=p=0", str(out)).strip()
    assert size == "300,300"
