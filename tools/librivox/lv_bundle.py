"""lv_bundle.py <work> <picks.txt> [genders.json]
Turn the chosen LibriVox clips into bundled voices: normalise like voices.add() (mono, 24 kHz, trimmed),
write src/folivox/voices/<id>.flac and rebuild catalog.json (existing entries are kept first).
picks.txt: one line per language, "<code> <clip name> <clip name> ...". Clips are looked up in
<work>/all_<code>/ (or ~/Desktop/folivox_voices/librivox_<code>/) and <work>/<code>_clips.json."""
import json, re, shutil, sys, tempfile
from pathlib import Path

import soundfile as sf

from folivox import voices

LANG_NAME = {"en": "English", "de": "German", "fr": "French", "es": "Spanish", "it": "Italian", "zh": "Chinese",
             "ja": "Japanese", "ko": "Korean", "ru": "Russian"}
work, picks = Path(sys.argv[1]), Path(sys.argv[2])
over = json.load(open(sys.argv[3])) if len(sys.argv) > 3 else {}  # {clip name: {"gender": "f", "text": "..."}}
desk = Path.home() / "Desktop/folivox_voices"
catalog = json.loads((voices.PACKAGE_DIR / "catalog.json").read_text(encoding="utf-8"))
have = {e["id"] for e in catalog}
tmp = Path(tempfile.mkdtemp()); voices.user_voices_dir = lambda: tmp
new = []
for line in picks.read_text().splitlines():
    code, *names = line.split()
    meta = {}
    cj = work / f"{code}_clips.json"
    if cj.exists(): meta = {r["name"]: r for r in json.load(open(cj)) if r["ok"]}
    ru_list = {}
    if code == "ru":  # the Russian run kept its metadata in СПИСОК.txt only
        for ln in (desk / "librivox_ru/СПИСОК.txt").read_text(encoding="utf-8").splitlines()[1:]:
            p = [x.strip() for x in ln.split("|")]
            ru_list[p[0]] = p
    readers = {}
    for n in names: readers.setdefault(n.rsplit("_", 2)[1], []).append(n)
    batch = []
    for n in names:
        rid, k = n.rsplit("_", 2)[1], n.rsplit("_", 1)[1]
        wav = next(p for p in (work / f"all_{code}" / f"{n}.wav", desk / f"librivox_{code}/{n}.wav") if p.exists())
        o = over.get(n, {})
        if code == "ru":
            p = ru_list[n]; reader = re.sub(r" \(LibriVox reader \d+\)", "", p[1]); book = p[2]; book_url = ""
            text = (desk / "librivox_ru" / f"{n}.txt").read_text(encoding="utf-8"); f0 = int(p[4].split()[0]); conf = 0
        else:
            m = meta[n]; reader, book, book_url = m["reader"].strip(), m["book"], m["book_url"]; text = m["text"]; f0 = m["f0"]; conf = m["conf"]
        gender = o.get("gender") or ("m" if f0 < 165 else "f")
        text = o.get("text", text)
        slug = re.sub(r"[^a-z0-9]+", "-", re.sub(r"[^\x00-\x7f]", lambda c: __import__("unicodedata").normalize("NFKD", c.group()).encode("ascii", "ignore").decode(), reader).lower()).strip("-")
        vid = f"{code}-{slug}" + (f"-{int(k) + 1}" if len(readers[rid]) > 1 else "")
        assert vid not in have, vid
        src = f"LibriVox reader {rid} «{reader}», «{book}»" + (f" ({book_url})" if book_url else "") + ", public-domain recording"
        e = voices.add(vid, wav, text, name=f"{LANG_NAME[code]} {'female' if gender == 'f' else 'male'} · {reader} (LibriVox)",
                       gender=gender, lang=code, source=src, license="Public domain", url=f"https://librivox.org/reader/{rid}")
        dur = sf.info(str(e.path)).frames / voices.TARGET_SR
        shutil.copy(e.path, voices.PACKAGE_DIR / f"{vid}.flac")
        d = e.to_meta(); batch.append((conf, d)); print(vid, gender, round(dur, 1), "s")
    new += [d for _, d in sorted(batch, key=lambda t: -t[0])]
(voices.PACKAGE_DIR / "catalog.json").write_text(json.dumps(catalog + new, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(len(new), "voices added")
