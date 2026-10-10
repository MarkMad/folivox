# Proposal: `folivox ui` — a local web interface

Status: **proposal**, nothing is implemented yet.

## Goal

A browser UI for people who do not want to type options: pick a book, hear a voice, try a short
preview, start the long render and watch it. Everything stays on the user's computer — the server binds
to `127.0.0.1`, there is no account, no telemetry, no cloud component. The CLI stays the primary
interface and keeps working unchanged; the UI is a second front end over the same code.

```bash
uv tool install "folivox[all,ui]"
folivox ui                  # opens http://127.0.0.1:8765
folivox ui --port 9000 --no-open
```

## Architecture

```
browser (static HTML + small JS)  ⇄  HTTP + SSE  ⇄  folivox.ui (Starlette)  →  folivox.pipeline.render()
```

- **Server:** [Starlette](https://www.starlette.io/) + uvicorn (two small dependencies, behind the optional
  extra `folivox[ui]`; the CLI and CI do not need them). FastAPI would add pydantic and auto-docs we
  do not need for ~12 endpoints; Starlette keeps the surface small. (Alternatives: stdlib `http.server`
  — no dependencies but hand-written SSE/multipart; Gradio/NiceGUI — fastest to build but heavy and
  hard to make look like an audiobook tool.)
- **Front end:** plain HTML/CSS + a few hundred lines of vanilla JS or htmx, shipped inside the package
  (`folivox/ui/static/`). No Node build step, works offline.
- **Jobs:** one render job at a time (the TTS model occupies the GPU/RAM). A job runs
  `pipeline.render()` in a worker thread. The UI implements the existing `Events` callbacks and
  pushes them to the browser as JSON over **Server-Sent Events** (`GET /api/jobs/{id}/events`):
  `stage`, `warning`, `plan`, `chunk_done` (with retakes/RTF), `chapter_built`, `done`, `error`.
  A late-connecting browser gets the current state first, so a page reload does not lose the job.
- **Resume:** the work directory and SQLite journal are already the source of truth. Starting a job on
  the same book + options simply continues; the UI shows "resume (63 % done)" by reading the journal.
- **Cancel:** needs one small core change — a cooperative check. `Events` gets an optional
  `cancelled() -> bool` polled between fragments (default `False`); `render()` stops cleanly with the
  journal consistent, exactly as after Ctrl+C. The CLI's `KeyboardInterrupt` path is unchanged.
- **Security:** bind to loopback only, refuse non-loopback `Host`/`Origin` headers (DNS-rebinding
  guard), random per-session token in the URL the CLI prints, uploads limited to book formats and
  stored in a temp dir, no path parameters taken from the browser (files are addressed by id).
  API keys are never accepted or stored by the UI — it only shows which environment variables are set.

## Screens (first version, one page with sections)

1. **Book** — drop a file (or pick a path). Shows title, author, detected language (editable), cover,
   estimated duration, the chapter tree — the output of `folivox inspect`.
2. **Chapters** — checkboxes per chapter (select all / range), live estimate of the selected length.
   Depth selector.
3. **Voice** — list of catalog voices (filtered by book language) with ▶ audition of the stored
   sample; upload your own sample (+ transcript field); link to voice design later. A short
   "read this sentence from your book" audition renders ~10 s with the selected voice through the
   normal TTS path (needs the model loaded once; cached for the session).
4. **Options** — the same groups as `folivox render --help` (Text / Quality control / Output …),
   collapsed by default, defaults and descriptions generated from the CLI option definitions so
   the two never drift apart.
5. **Preview** — renders the first N characters of the first selected chapter (`--preview`) and plays
   it in the browser. The fast loop to check voice, speed and pronunciation before a 10-hour run.
6. **Render** — Start / Pause (= cancel, resumable) / Resume. Progress bar (characters done / total),
   elapsed, remaining, RTF, retakes, a log of stages and warnings, finished chapters playable as soon
   as they are built. On completion: path to the `.m4b`, "show in folder".
7. **Settings** — providers per kind (`tts`, `asr`, `llm`, `voicegen`) from the registry
   (`folivox providers`), local vs cloud badge with the "your text leaves this computer" warning, model
   directory, device. Writes the same `config.toml` (never keys).

## API sketch

| Method | Path | |
|---|---|---|
| POST | `/api/books` | upload → `{book_id, title, author, lang, chapters[], estimated_seconds}` |
| GET | `/api/voices` | catalog (id, name, lang, license) |
| GET | `/api/voices/{id}/sample` | audio for audition |
| POST | `/api/preview` | `{book_id, voice, options}` → `{audio_url}` (synchronous, short) |
| POST | `/api/jobs` | start render `{book_id, voice, chapters, options}` → `{job_id}` (409 if busy) |
| GET | `/api/jobs/{id}/events` | SSE stream of pipeline events |
| POST | `/api/jobs/{id}/cancel` | cooperative stop |
| GET | `/api/jobs/{id}/chapters/{n}.mp3` | built chapter audio |
| GET/PUT | `/api/settings` | providers and paths (no secrets) |

## Required core changes (small, CLI-neutral)

- `Events.cancelled()` hook (above).
- Option metadata shared between the Typer CLI and the UI (one list of option name, type, default,
  help, group) so the Options screen is generated, not copied.
- A function returning book structure as plain data (already what `inspect` prints).

## Scope and phasing

- **v0 (minimal first version):** Book → Chapters → Voice (catalog + audition) → Preview → Render with
  live progress, cancel/resume. Providers shown read-only. ~600 lines Python + ~400 lines JS, 8–10 tests
  (API with Starlette's `TestClient`, a fake `render` that emits events).
- **v1:** voice upload and design, settings editor, playing finished chapters, multiple queued jobs.
- **Out of scope:** accounts, remote access, hosted deployment, editing the book text in the UI.

## Open questions

1. Starlette (recommended) vs. FastAPI vs. a heavier all-in-one toolkit (Gradio/NiceGUI)?
2. Is the v0 scope above right, or should it start smaller (inspect + render progress only)?
3. Should `folivox ui` open the browser automatically (default) or just print the URL?
