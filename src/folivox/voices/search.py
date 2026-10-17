"""Find a clean 6–15 s stretch of one person's speech in a long recording (a video, a podcast, a film).

Cheap signal analysis narrows hours of sound down to a few promising windows, then speech recognition
checks that each one really is speech in the expected language. No extra models are needed.

1. ffmpeg decodes the audio track to 16 kHz mono and the stream is cut into 30 ms frames (never all in memory).
2. Per frame: level, share of energy in the speech band, and how periodic it is (pitch 70–400 Hz).
3. Speech frames are joined into phrases; phrases with no pitch (noise, effects) or a flat level (music) go.
4. Windows of neighbouring phrases of 6–15 s are scored: signal over the quiet parts, share of speech,
   pauses, clipping, a steady pitch (a change of voice between phrases hints at a second speaker).
5. The best non-overlapping windows are transcribed; text that does not fit the length or the language
   (music, a song, speech in another language) lowers the rank.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

VIDEO_EXTS = frozenset(".mp4 .m4v .mkv .mov .webm .avi .wmv .flv .ts .mts .m2ts .mpg .mpeg .3gp .ogv".split())

ANALYSIS_SR = 16000
VOICE_SR = 24000
FRAME = 480  # 30 ms at 16 kHz
FRAME_S = FRAME / ANALYSIS_SR
MIN_LEN, MAX_LEN, BEST_LEN = 6.0, 15.0, 10.0
PAD = 0.12  # seconds kept around a window so no word is clipped


class NothingFound(RuntimeError):
    pass


@dataclass
class Candidate:
    start: float
    end: float
    score: float
    text: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end - self.start


def needs_search(path: Path) -> bool:
    """True when ``path`` is a video or an audio file too long to be a voice sample as it is."""
    from folivox.tts.voice import MAX_SECONDS, audio_duration

    if path.suffix.lower() in VIDEO_EXTS:
        return True
    try:
        return audio_duration(path) > MAX_SECONDS
    except Exception:  # noqa: BLE001 — a format libsndfile cannot read (m4a, aac…): ffmpeg takes it
        return path.suffix.lower() not in {".wav", ".flac", ".ogg", ".mp3"}


def probe(path: Path) -> tuple[float | None, bool]:
    """(duration in seconds or None, has an audio track)."""
    from folivox.audio.assemble import ffmpeg

    proc = subprocess.run([ffmpeg(), "-hide_banner", "-i", str(path)], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    err = proc.stderr
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", err)
    dur = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else None
    return dur, bool(re.search(r"Stream #.*Audio:", err))


def decode_chunks(path: Path, start: float = 0.0, length: float | None = None, sr: int = ANALYSIS_SR,
                  block_s: float = 60.0):
    """Yield float32 mono blocks of the first audio track."""
    from folivox.audio.assemble import ffmpeg

    cmd = [ffmpeg(), "-v", "error", "-nostdin"]
    if start > 0:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(path)]
    if length is not None:
        cmd += ["-t", f"{length:.3f}"]
    cmd += ["-map", "0:a:0", "-vn", "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    size = int(block_s * sr) * 2
    try:
        while True:
            buf = proc.stdout.read(size)
            if not buf:
                break
            buf = buf[: len(buf) // 2 * 2]
            yield np.frombuffer(buf, dtype="<i2").astype(np.float32) / 32768.0
    finally:
        proc.stdout.close()
        err = proc.stderr.read().decode("utf-8", "replace").strip()[-1500:]
        proc.stderr.close()
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        if proc.returncode not in (0, None) and proc.returncode > 0:
            raise RuntimeError(f"ffmpeg failed:\n{err}")


def decode(path: Path, start: float, length: float, sr: int) -> np.ndarray:
    parts = list(decode_chunks(path, start, length, sr, block_s=length + 1))
    return np.concatenate(parts) if parts else np.zeros(0, np.float32)


# ── frame features ────────────────────────────────────────────────────────────

_NFFT = 1024
_BIN = ANALYSIS_SR / _NFFT
_BAND = (int(300 / _BIN), int(3400 / _BIN))
_LAGS = (ANALYSIS_SR // 400, ANALYSIS_SR // 70)


@dataclass
class Frames:
    db: np.ndarray
    band: np.ndarray
    voicing: np.ndarray
    f0: np.ndarray
    peak: np.ndarray

    @classmethod
    def empty(cls) -> Frames:
        z = np.zeros(0, np.float32)
        return cls(z, z, z, z, z)

    def extend(self, other: Frames) -> Frames:
        return Frames(*(np.concatenate([a, b]) for a, b in zip(
            (self.db, self.band, self.voicing, self.f0, self.peak),
            (other.db, other.band, other.voicing, other.f0, other.peak), strict=True)))


def frame_features(x: np.ndarray) -> Frames:
    """Features of whole 30 ms frames of ``x`` (a tail shorter than a frame is dropped)."""
    n = len(x) // FRAME
    if n == 0:
        return Frames.empty()
    fr = x[: n * FRAME].reshape(n, FRAME)
    db = 20 * np.log10(np.sqrt((fr**2).mean(axis=1)) + 1e-9)
    peak = np.abs(fr).max(axis=1)
    out = [np.empty(n, np.float32) for _ in range(3)]
    band, voicing, f0 = out
    step = 8192  # frames per batch: bounds the size of the FFT arrays
    for a in range(0, n, step):
        w = fr[a:a + step] * np.hanning(FRAME).astype(np.float32)
        spec = np.fft.rfft(w, _NFFT, axis=1)
        power = spec.real**2 + spec.imag**2
        total = power.sum(axis=1) + 1e-12
        band[a:a + step] = power[:, _BAND[0]:_BAND[1]].sum(axis=1) / total
        ac = np.fft.irfft(power, _NFFT, axis=1)[:, :_LAGS[1] + 1]
        lag = _LAGS[0] + ac[:, _LAGS[0]:].argmax(axis=1)
        voicing[a:a + step] = ac[np.arange(len(ac)), lag] / (ac[:, 0] + 1e-12)
        f0[a:a + step] = ANALYSIS_SR / lag
    return Frames(db.astype(np.float32), band, voicing, f0, peak.astype(np.float32))


def analyse_file(path: Path, start: float = 0.0, end: float | None = None,
                 progress: Callable[[float], None] | None = None, total: float | None = None) -> Frames:
    frames = Frames.empty()
    length = None if end is None else max(0.0, end - start)
    carry = np.zeros(0, np.float32)
    done = 0.0
    span = length if length is not None else (max(0.0, total - start) if total else None)
    for block in decode_chunks(path, start, length):
        x = np.concatenate([carry, block])
        cut = len(x) // FRAME * FRAME
        carry = x[cut:]
        frames = frames.extend(frame_features(x[:cut]))
        done += len(block) / ANALYSIS_SR
        if progress and span:
            progress(min(1.0, done / span))
    return frames


# ── phrases and windows ───────────────────────────────────────────────────────

@dataclass
class _Phrase:
    a: int  # first frame
    b: int  # one past the last frame
    f0: float
    voiced: float


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    if not mask.any():
        return []
    edges = np.diff(np.concatenate([[0], mask.astype(np.int8), [0]]))
    return list(zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1), strict=True))


def _phrases(fr: Frames, floor: float) -> tuple[np.ndarray, list[_Phrase]]:
    speech = (fr.db > floor + 10) & (fr.band > 0.5)
    # close gaps shorter than 0.25 s: pauses between sounds of one word are not phrase borders
    gap = int(0.25 / FRAME_S)
    joined = speech.copy()
    runs = _runs(speech)
    for (_, e0), (s1, _) in zip(runs, runs[1:], strict=False):
        if s1 - e0 <= gap:
            joined[e0:s1] = True
    out = []
    for a, b in _runs(joined):
        if (b - a) * FRAME_S < 0.4:
            continue
        seg = slice(a, b)
        voiced = (fr.voicing[seg] > 0.45)
        share = float(voiced.mean())
        if share < 0.25:  # no pitch: noise, effects, whispering
            continue
        if float(fr.db[seg][joined[seg]].std()) < 4.0:  # an even level: music, a drone, a tone
            continue
        f0 = float(np.median(fr.f0[seg][voiced])) if voiced.any() else 0.0
        out.append(_Phrase(a, b, f0, share))
    return joined, out


def find_windows(fr: Frames) -> list[Candidate]:
    """Every 6–15 s run of neighbouring phrases, scored 0..1 (most promising first)."""
    if len(fr.db) < int(MIN_LEN / FRAME_S):
        return []
    floor = float(np.percentile(fr.db, 10))
    speech, phrases = _phrases(fr, floor)
    cands: list[Candidate] = []
    max_gap = int(1.5 / FRAME_S)
    for i, first in enumerate(phrases):
        for j in range(i, len(phrases)):
            last = phrases[j]
            if j > i and phrases[j].a - phrases[j - 1].b > max_gap:
                break
            span = (last.b - first.a) * FRAME_S
            if span > MAX_LEN:
                break
            if span < MIN_LEN:
                continue
            seg = slice(first.a, last.b)
            group = phrases[i:j + 1]
            spk = speech[seg]
            quiet = fr.db[seg][~spk]
            noise = float(np.median(quiet)) if len(quiet) >= 5 else floor
            level = float(np.median(fr.db[seg][spk]))
            snr = (np.clip((level - noise - 8) / 22, 0, 1))
            dens = float(spk.mean())
            dens_s = min(1.0, dens / 0.6) if dens < 0.97 else 0.7
            voiced = float(np.average([p.voiced for p in group], weights=[p.b - p.a for p in group]))
            length_s = 1.0 if 8 <= span <= 13 else 0.75
            score = 0.45 * snr + 0.2 * dens_s + 0.15 * length_s + 0.2 * min(1.0, voiced / 0.5)
            if float((fr.peak[seg] >= 0.98).mean()) > 0.005:  # clipping
                score *= 0.5
            pitches = [p.f0 for p in group if p.f0 > 0]
            if pitches and max(pitches) / min(pitches) > 1.4:  # another voice may speak in between
                score *= 0.5
            cands.append(Candidate(first.a * FRAME_S, last.b * FRAME_S, float(score)))
    cands.sort(key=lambda c: -c.score)
    return cands


def pick_distinct(cands: list[Candidate], n: int, min_gap: float = 5.0) -> list[Candidate]:
    """The best ``n`` windows that do not overlap each other or sit within ``min_gap`` seconds."""
    out: list[Candidate] = []
    for c in cands:
        if all(c.end + min_gap <= o.start or c.start >= o.end + min_gap for o in out):
            out.append(c)
            if len(out) == n:
                break
    return out


# ── the whole search ──────────────────────────────────────────────────────────

def find_samples(path: Path, lang: str, asr=None, *, count: int = 3, start: float = 0.0, end: float | None = None,
                 progress: Callable[[float, str], None] | None = None) -> list[Candidate]:
    """Up to ``count`` samples of 6–15 s, best first. ``asr`` is a recogniser (``Transcriber(language=lang)``)."""
    from folivox.tts.voice import transcript_warnings

    path = Path(path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    total, has_audio = probe(path)
    if not has_audio:
        raise NothingFound("The file has no audio track.")
    say = progress or (lambda *_: None)
    fr = analyse_file(path, start, end, lambda f: say(f * 0.7, "analysing"), total)
    pool = pick_distinct(find_windows(fr), max(6, count * 3))
    if not pool:
        raise NothingFound("No clean stretch of speech of 6–15 s found: the recording is music, noise or "
                           "speech with no pauses. Try another part with --from/--to.")
    for c in pool:  # frame times are relative to ``start``
        c.start += start
        c.end += start
    if asr is None:
        return pool[:count]
    checked = []
    for k, c in enumerate(pool):
        say(0.7 + 0.3 * k / len(pool), "recognising")
        a = max(0.0, c.start - PAD)
        x = decode(path, a, c.duration + 2 * PAD, ANALYSIS_SR)
        text = " ".join((asr.transcribe(x, ANALYSIS_SR) or "").split())
        c.text = text
        c.warnings = transcript_warnings(text, c.duration, lang)
        if not any(ch.isalpha() for ch in text):
            c.warnings.append("No speech was recognised in this stretch.")
            c.score *= 0.1
        elif c.warnings:
            c.score *= 0.4
        checked.append(c)
        if len([d for d in checked if not d.warnings]) >= count and k + 1 >= count:
            break
    checked.sort(key=lambda c: -c.score)
    say(1.0, "done")
    return checked[:count]


def cut(path: Path, cand: Candidate, out: Path) -> Path:
    """Write the candidate as a mono 24 kHz WAV (with a little margin on both sides)."""
    import soundfile as sf

    a = max(0.0, cand.start - PAD)
    x = decode(Path(path), a, cand.duration + 2 * PAD, VOICE_SR)
    if not len(x):
        raise NothingFound("Nothing could be decoded at that position.")
    sf.write(str(out), x, VOICE_SR, subtype="PCM_16")
    return out


def parse_time(s: str) -> float:
    """``90``, ``1:30`` or ``1:02:03`` → seconds."""
    parts = [float(p) for p in s.strip().split(":")]
    if not 1 <= len(parts) <= 3 or any(p < 0 for p in parts):
        raise ValueError(f"Bad time {s!r}: use seconds, mm:ss or h:mm:ss")
    t = 0.0
    for p in parts:
        t = t * 60 + p
    return t
