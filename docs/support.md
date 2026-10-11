# Troubleshooting and the support bundle

## Resuming is automatic

Every finished fragment is saved in the work folder (`BOOK.folivox/`, next to the output). Run the same
command again, or press **Render** again in the studio, and Folivox continues from the first unfinished
fragment. Damaged files (an empty or cut-off fragment after a crash or power loss) are detected at the start
and synthesised again. An earlier finished book is never replaced until the new one is fully written.

Before a long render starts, Folivox checks ffmpeg, that the output and work folders are writable and how much
disk is free, so a missing ffmpeg does not show up after ten hours of synthesis.

## What is retried, and what is not

- Model download: up to 4 attempts, continuing from the part already downloaded.
- A model that fails on the GPU (`mps`/`cuda`) is loaded on the CPU instead, with a warning (slower).
- Speech recognition (quality check) that cannot load or fails on a fragment: the render goes on without the check.
- Online engines: timeouts, 429 and 5xx are retried with growing, randomised pauses. If the network or the provider
  is down, Folivox waits (up to 30 minutes, cancel works during the pause) and continues; after that it stops with
  progress saved. Wrong key, exhausted credits and rejected requests are not retried and are not counted as spent.
  A fragment is counted once however many times the request is repeated, and the spending cap is checked first.

## Log file

A structured log (one JSON object per line, 1 MB × 5 files, rotated) is written to the per-user log folder:
macOS `~/Library/Logs/folivox`, Windows `%LOCALAPPDATA%\folivox\Logs`, Linux `~/.local/state/folivox/log`.
It records versions, engine and options (no secrets, no book text), timings and tracebacks.

## Support bundle

```bash
folivox doctor                      # print the health report
folivox doctor --bundle ~/Desktop   # also save a redacted zip
folivox doctor --bundle out.zip --work "My Book.folivox"   # include progress counters of one render
```

In the studio: **Advanced settings → Copy diagnostics** (text for a message) or **Save a support bundle** (zip).

The bundle holds `report.json` (platform, Python, package versions, ffmpeg, devices, selected engines, model folder
state, free disk, journal counters), `folivox.log` (tail) and a README. API keys and tokens are removed (also from the
log), the book text is never included (messages carry at most a 40-character snippet), nor audio or voice
recordings. Home paths appear as `~`. Look inside before you share it; nothing is sent anywhere automatically.

Set `FOLIVOX_FFMPEG=/path/to/ffmpeg` if ffmpeg is installed somewhere Folivox does not find it.
