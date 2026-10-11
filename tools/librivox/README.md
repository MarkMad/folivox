# LibriVox voice-sample tools (research scripts, not part of the package)

Pipeline used to find public-domain reader samples for the Folivox voice catalog (all scripts take a work dir as first argument):

1. `lv_scan.py <work>` – whole catalog (≈22 400 books, with genres) via https://librivox.org/api/info into `lv_books.json`.
2. `lv_readers.py <work> <Language> <max_books> [--poetry]` – per book (`extended=1`): sections with reader, playtime, mp3 url (seeded sample if there are more books than the cap; verse/drama/sermon genres skipped unless `--poetry`).
3. `lv_dl.py <work> <Language> <code> <max_readers> [min_section_s]` – per reader picks 2 sections (single-reader, non-verse) and downloads ~45 s from the middle with an HTTP Range request (≈360 KB).
4. `lv_cut.py <work> <code>` – Whisper (word timestamps, per-language prompt) -> 8–15 s window between sentence boundaries (pauses as fallback), wav + transcript + `СПИСОК.txt`; announcements skipped; F0 and chars/s computed.
5. `lv_pack.py <work> <code> [per_gender]` – keeps the best prose candidates (no duplicates, Whisper confidence, ≤2 clips per reader, low/high F0 balance) and zips them.

Notes: send a descriptive User-Agent (the default Python one gets 403), pause ≥1 s between requests, the per-section `language` field is unreliable (filter by the book's language), mp3s are 64 kbps so byte offset = seconds × 8000. Sections that list several readers are skipped (speaker is ambiguous).
