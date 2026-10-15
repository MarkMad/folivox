"""Render journal: the plan (chunks per chapter) and finished takes, in SQLite.

Audio of every accepted take is stored as ``audio/<key>.flac`` where ``key`` hashes the model
input text, the voice and synthesis settings. A chunk is done when its key has a row in
``takes`` and the file exists, so an interrupted render resumes exactly where it stopped, and a
changed plan (other normalisation, chunk size) only re-synthesises chunks whose text changed.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from folivox.text.chunk import Chunk

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS chapters (idx INTEGER PRIMARY KEY, title TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS chunks (
    chapter INTEGER NOT NULL, idx INTEGER NOT NULL, key TEXT NOT NULL,
    text TEXT NOT NULL, source TEXT NOT NULL, pause REAL NOT NULL, kind TEXT NOT NULL,
    PRIMARY KEY (chapter, idx)
);
CREATE INDEX IF NOT EXISTS chunks_key ON chunks(key);
CREATE TABLE IF NOT EXISTS takes (
    key TEXT PRIMARY KEY, duration REAL NOT NULL, score REAL, asr TEXT, takes INTEGER NOT NULL,
    synth_seconds REAL NOT NULL, created REAL NOT NULL
);
"""


def chunk_key(text: str, voice_id: str, settings: str, speaker: str = "", markup: str = "") -> str:
    """Identity of a take. ``settings`` carries the engine, its build and the synthesis version; ``speaker`` and
    ``markup`` (expression tags, delivery cues) are part of the key only when used, so keys of single-voice
    renders made before multi-voice existed stay valid."""
    base = f"{settings}\x1f{voice_id}\x1f{text}"
    if speaker or markup:
        base += f"\x1f{speaker}\x1f{markup}"
    return hashlib.sha1(base.encode()).hexdigest()[:24]


@dataclass
class PlannedChunk:
    chapter: int
    idx: int
    key: str
    text: str
    source: str
    pause: float
    kind: str


@dataclass
class Take:
    key: str
    duration: float
    score: float | None
    asr: str | None
    takes: int
    synth_seconds: float


class Journal:
    def __init__(self, work_dir: Path):
        self.dir = Path(work_dir)
        self.audio_dir = self.dir / "audio"
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.dir / "journal.sqlite", isolation_level=None)  # autocommit
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    # -- meta
    def set_meta(self, **values) -> None:
        for k, v in values.items():
            self.db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (k, json.dumps(v, ensure_ascii=False)))

    def meta(self, key: str, default=None):
        row = self.db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    # -- plan
    def set_plan(self, chapters: list[tuple[str, list[Chunk]]], voice_id: str, settings: str) -> None:
        with self.db:
            self.db.execute("BEGIN")
            self.db.execute("DELETE FROM chapters")
            self.db.execute("DELETE FROM chunks")
            for ci, (title, chunks) in enumerate(chapters):
                self.db.execute("INSERT INTO chapters VALUES (?, ?)", (ci, title))
                self.db.executemany(
                    "INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [(ci, c.index, chunk_key(c.text, voice_id, settings), c.text, c.source, c.pause_after, c.kind)
                     for c in chunks])

    def chapters(self) -> list[tuple[int, str]]:
        return list(self.db.execute("SELECT idx, title FROM chapters ORDER BY idx"))

    def chunks(self, chapter: int | None = None) -> list[PlannedChunk]:
        q = "SELECT chapter, idx, key, text, source, pause, kind FROM chunks"
        args: tuple = ()
        if chapter is not None:
            q += " WHERE chapter = ?"
            args = (chapter,)
        return [PlannedChunk(*r) for r in self.db.execute(q + " ORDER BY chapter, idx", args)]

    # -- takes
    def audio_path(self, key: str) -> Path:
        return self.audio_dir / f"{key}.flac"

    def _has_audio(self, key: str) -> bool:
        try:
            return self.audio_path(key).stat().st_size > 0
        except OSError:
            return False

    def is_done(self, key: str) -> bool:
        row = self.db.execute("SELECT 1 FROM takes WHERE key = ?", (key,)).fetchone()
        return bool(row) and self._has_audio(key)

    def audit(self, tolerance: float = 0.5) -> list[str]:
        """Forget takes whose audio file is missing, empty, unreadable or of a different length than recorded
        (power loss, disk errors, manual edits), so they are synthesised again. Returns the forgotten keys."""
        from folivox.audio import audio_seconds

        bad = []
        for key, duration in list(self.db.execute("SELECT key, duration FROM takes")):
            got = audio_seconds(self.audio_path(key)) if self._has_audio(key) else None
            if got is None or abs(got - duration) > max(tolerance, duration * 0.02):
                bad.append(key)
        for key in bad:
            self.db.execute("DELETE FROM takes WHERE key = ?", (key,))
            self.audio_path(key).unlink(missing_ok=True)
        return bad

    def pending(self) -> list[PlannedChunk]:
        done = {k for (k,) in self.db.execute("SELECT key FROM takes")}
        return [c for c in self.chunks() if c.key not in done or not self._has_audio(c.key)]

    def record(self, take: Take) -> None:
        self.db.execute("INSERT OR REPLACE INTO takes VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (take.key, take.duration, take.score, take.asr, take.takes, take.synth_seconds, time.time()))

    def take(self, key: str) -> Take | None:
        row = self.db.execute("SELECT key, duration, score, asr, takes, synth_seconds FROM takes WHERE key = ?",
                              (key,)).fetchone()
        return Take(*row) if row else None

    def stats(self) -> dict:
        total_chars = done_chars = 0
        audio = synth = 0.0
        done = {r[0]: r for r in self.db.execute("SELECT key, duration, synth_seconds FROM takes")}
        for c in self.chunks():
            total_chars += len(c.source)
            if c.key in done:
                done_chars += len(c.source)
                audio += done[c.key][1]
                synth += done[c.key][2]
        return {"total_chars": total_chars, "done_chars": done_chars, "audio_seconds": audio,
                "synth_seconds": synth}

    def flagged(self, threshold: float | None = None, lang: str | None = None) -> Iterable[tuple[PlannedChunk, Take]]:
        """Fragments whose kept take still fails QA after every retake (and split): the ones to listen to.
        ``threshold`` and ``lang`` default to what the render recorded; the limit per fragment is the
        same as during the render (short lines get more slack)."""
        from folivox.qa import threshold_for

        base = threshold if threshold is not None else self.meta("qa_threshold")
        if base is None:
            return
        lang = lang or self.meta("lang") or "ru"
        for c in self.chunks():
            t = self.take(c.key)
            if t and t.score is not None and t.score > threshold_for(c.source, base, lang):
                yield c, t
