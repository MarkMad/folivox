# LibriVox voice-sample tools (research scripts, not part of the package)

Pipeline used to find public-domain reader samples for the Folivox voice catalog:

1. `lv_scan.py` – downloads the whole catalog (≈22 400 books) via https://librivox.org/api/info and counts books per language.
2. `lv_readers.py <Languages> <out.json>` – per book (`extended=1`): sections with reader, playtime and mp3 url.
3. `lv_dl.py` – per reader picks 2 sections from different books and downloads ~26 s from the middle with an HTTP Range request (≈200 KB, not the whole chapter).
4. `lv_cut.py` – Whisper segments → 8–15 s windows between sentence boundaries, writes wav + transcript.

Notes: send a descriptive User-Agent (the default Python one gets 403), pause ≥1 s between requests, the per-section `language` field is unreliable (filter by the book's language), mp3s are 64 kbps so byte offset = seconds × 8000.
The scripts are tuned for Russian (cut windows by `[.!?]`, capital letters) and use hard-coded scratchpad paths; generalise before reuse.
