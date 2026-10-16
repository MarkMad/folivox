# Speakers and expression tags (markup)

A book can have **several voices** (a narrator and characters) and **expression tags** (`[sighs]`,
`[whispering]`…). The markup is a separate layer: it never contains or changes the book text. It is stored in
`BOOK.markup.json` next to the book (the studio keeps its own copy per uploaded book) and `folivox render`
picks it up by itself; `--no-markup` ignores it, `--markup FILE` names another file.

Books without markup are read exactly as before.

## What it says

- **Speakers**: id 0 is the narrator and reads everything not given to someone else; ids 1–15 are characters
  (the range of Fish's `<|speaker:N|>` tags). Each speaker has a name and optionally a **voice**: an id from
  `folivox voices` or a path to a recording. A speaker without a voice is read with the book's main voice.
- **Spans**: a range of characters inside a paragraph belongs to a speaker, optionally with delivery tags put
  in front of it. A paragraph can be split between narrator and characters («— Ты куда? — спросила соседка»).
- **Marks**: an inline expression tag at an offset, where the effect should happen.
- The markup remembers a signature of each chapter's text. If you replace the book with another edition,
  chapters whose text changed are ignored (the narrator reads them) and `folivox markup check` says so.

Every fragment is read by one speaker with that speaker's voice; the voice, the speaker and the tags are part
of the fragment's cache key, so changing one re-renders only what it touches.

Expression tags are written into the text only for the Fish engines (`fish-s2`, `fish-drama3`); other engines
read the text without them. `--no-expression-tags` turns them off for a render, and the markup can switch them
off for the book (`@expression_tags off`). Characters may use different voices with every local engine; a
cloud engine reads the whole book in one voice.

With a Fish engine each speaker's voice must be your own recording, a generated voice, or the voice of someone
who agreed: the bundled voices are not used (see [Fish Audio engines](fish-engines.md#voices-of-real-people)).

## Working with the markup in the console

```bash
folivox markup export book.epub -o book.txt           # text form (an empty template if there is no markup yet)
folivox markup import book.epub book.txt              # read it back, check it, save BOOK.markup.json
folivox markup speaker book.epub 1 --name Anna --voice anna.wav --gender f
folivox markup speakers book.epub                     # who reads how much, which voice exists
folivox markup check book.epub                        # stale chapters, bad spans, unknown tags, missing voices
folivox markup tags --category emotion                # the tag list
folivox markup clear book.epub
```

The **text form** is one line per paragraph with Fish-style tags inserted:

```
@speaker 0 | Narrator |  |
@speaker 1 | Anna | anna.wav | f
@expression_tags on

## chapter 1: Home
B1.0  <|speaker:1|> [whispering] Ты куда? <|speaker:0|> — спросила соседка.
```

`<|speaker:N|>` switches the speaker until the next tag; `[tag]` is an expression tag at that spot. When you
import, Folivox removes every tag and checks that what is left is exactly the book's paragraph: an edit that
changes the text is refused and names the line. (Paragraphs with line breaks, such as poems, are not in the
text form; use the JSON.) `--format json` exports the stored form.

## Expression tags

`src/folivox/tts/expression_tags.json` lists the tags the vendors document, by category (emotion, tone, sound,
effect, pause), with the model they were seen for and the source page (the S2 Pro model card, the Drama 3 model
card and Fish Audio's emotion documentation, retrieved 2026-10-15). It holds only the short tag names. The
models take **free-form** tags, so a tag that is not in the list is kept (and flagged by `markup check`);
the list feeds the editor's picker and the prompts of the automatic markup. Fish advises at most three tags
per sentence, emotions at the start of a sentence, `[emphasis]` right before the word. Drama 3's own card shows
only `[sighs]` and `[laughs]`; the others were documented for S2 and are expected to work, listen first.

Refresh the list with `python tools/fish_tags.py` (prints tags found in the vendors' pages that the database
does not have yet).

## Automatic markup with a language model

A local model (or an API you choose) can find the characters and mark who speaks each part. It only
*annotates*: the text is never taken from the model.

```bash
folivox markup models                        # which Gemma 4 suits this computer, what is installed
folivox markup analyse book.epub             # read the book once: who is in it, how many voices it needs
folivox markup characters book.epub          # show the saved list again
folivox markup auto book.epub                # mark the speakers (--chapters 1-3, --expression-tags)
```

**Models.** Gemma 4 is multilingual and comes in sizes for different memory; Folivox proposes the largest that
fits (`gemma4:31b-it-qat` from 48 GB, `26b-a4b-it-qat` from 32 GB, `12b-it-qat` for everything smaller) and
you can use any other Ollama model, or an OpenAI-compatible API (`--llm openai --model NAME`, your key, the text
goes to that service). Set a default in `config.toml`: `[llm.ollama] model = "gemma4:12b-it-qat"`. The analysis
runs before the audio is made, never together with the voice model. Small models miss subtle speakers: check
the result.

A small test on an Apple-silicon Mac with 36 GB (made-up texts of 20 paragraphs, 15 with speech, the same story in
English, Russian, German and Spanish; counted: paragraphs whose quoted speech went to the right character):

| Model (Ollama) | English | Russian | German | Spanish | Time per text |
|---|---|---|---|---|---|
| `gemma4:31b-it-qat` | 15/15 | 15/15 | 15/15 | 3/15 | 4-5 min |
| `Qwen3.8-27B` (unsloth GGUF, UD-Q6_K, 22 GB) | 15/15 | 15/15 | not run | 15/15 | 4-5 min |
| `gemma4:12b-it-qat` | 15/15 | 15/15 | 3/15 | 12/15 | 1.2-1.6 min |
| Ministral-3-3B-Instruct-2512 (Q4_K_M) | 0/15 | 9/15 | 11/15 | 11/15 | 0.5 min |
| tiny-aya-global 3.3B (Q4_K_M) | 0/15 | 0/15 | 7/15 | 0/15 | 0.4 min |
| LFM2.5-2.6B (Q4_K_M) | 0/15 | 0/15 | 5/15 | 0/15 | 2-3 min |
| EuroLLM-9B-Instruct-2512 (Q4_K_M) | 0/15 | 4/15 | 0/15 | 0/15 | 1-2 min |

One run each, so read it as a rough picture. What it shows: only the large models (27-31B) were right on the
languages they got; the 12B model is good on English and Russian and shaky on German; the 3B models and the
small language-specific ones (Cohere tiny-aya, Liquid LFM2.5, EuroLLM) return the text unmarked or rewritten and
are not usable. The score is not only about the model: Spanish dialogue puts a dash that both closes the speech
and opens the attribution («—Perdone —graznó el anciano—, busco…»), and even the 31B model then rewrote the
punctuation, so the check "removing the marks gives the book's paragraph" refused 12 of 15 paragraphs. Asking the
model for *where* each speaker's words start, instead of repeating the whole paragraph, would be sturdier.

The two smallest Gemma 4 builds (`e4b` 6 GB, `e2b` 4 GB) were tried and **dropped from the list**: they are about ten
times faster, but unstable. `e2b` worked only on English (10/15) and returned unmarked text for Russian, German
and Spanish (0/15); `e4b` handled all four languages (9-12/15) but the same English text gave 0/15 once and
12/15 on the next run, and an unreliable result is worse than a slow one. A speaker tag with a missing bar
(`<|speaker:1>`) is understood, and a paragraph that starts with a dialogue dash with no space after it (Spanish «—¿Vas?») counts as speech.

**Character list ("bible").** `analyse` goes through the book in windows of about 5000 characters. For each
window the model gets the characters found so far (those named in the window, those active in the last windows
and the busiest) and reports who speaks, thinks or matters, with aliases, gender, age, speech traits,
relations and the number of lines. Names are merged across cases and nicknames ("Анна", "Анну", "Аня"). It
lists the characters in `BOOK.characters.json` with the number of **voices the book needs** (the narrator plus
every character with at least three lines), so you can choose voices before rendering. First-person narration,
unnamed speakers ("old guard"), thoughts and letters are covered by the prompt; the prompt names the dialogue
conventions of all nine book languages. Up to 15 characters get an id of their own; the rarest share ids 14
(men) and 15 (women).

**Marking.** `auto` takes the paragraphs that contain speech and asks the model to repeat each one with
`<|speaker:N|>` markers (and, with `--expression-tags`, `[tag]`s from the tag list, at most one per sentence).
The model gets the relevant bible entries and the last few marked paragraphs, so "he said" and pronouns resolve
across chapters, and may add or correct entries as it reads. The answer is accepted for a paragraph only if
removing the markers gives exactly the book's paragraph (whitespace differences are tolerated), the speaker
exists and the tags are in the tag list. Otherwise the narrator reads that paragraph. The summary at the end
counts how many fell back. Expression tags are a separate switch, off by default: the models already read
emotion reasonably well on their own.

Everything is **cached and resumable**: the replies are kept in `BOOK.llm-cache.sqlite` and the list and the
markup are saved after every window, so an interrupted run continues where it stopped and an unchanged window
is never asked twice (`--fresh` forgets the replies). The result is the ordinary markup file: export it as
text, fix what the model got wrong, import it back, assign voices with `folivox markup speaker`.

## Studio: the markup editor

Several voices are an **optional extra**: most books sound fine read by one voice. The box **Different voices for
characters** in *1 · Book* is collapsed and says so. Open it for one button, **Voice the characters
automatically**: it finds the characters, marks who speaks (with the installed model that fits this computer best) and shows
how many voices the book needs and which character still needs a voice. If no language model is installed the box
says so in one sentence and gives the command (`ollama pull <model>`). **Advanced settings** opens the editor.

**Time.** The box shows an estimate *before* you press the button and the progress line shows the time left while it
works. The estimate counts the model calls the run needs (the server's `/llm/estimate`) and turns them into time by
the model's size; it is a rough guess. During a run the speed is measured and the estimate corrected, and the speed
of the last run is remembered in the browser for that model. A long estimate suggests trying one chapter first.

Once the book has markup the box shows a one-line summary, **Review and fine-tune**, **Run again** and the switch
*Use the markup when rendering*.

In the editor the top of the right panel holds the one **Mark automatically** button with the choice *Whole book* /
*Only this chapter* (each with its own estimate), a progress bar and a plain result. *Options* (collapsed) holds the
model, *also place expression tags* and *Analyse characters* alone. After a run the panel lists the characters and
offers the next step (*Choose voices*, or reading the text through when everyone has a voice). Coloured chips assign
the selection to a speaker. Running again asks first, because passages you changed by hand may be replaced. The top
bar has the chapter picker, undo and redo (the arrows), Save and a close cross.

Below the button the manual tools are always visible:

- The **text** of the chapter is shown with every passage coloured by its speaker; the narrator's text has no
  colour. Pick the chapter in the list at the top (or with the arrows).
- **Assign**: select text (it may span paragraphs) and click a speaker in the panel on the right, or press the
  speaker's number key (0–9). *Clear selection* gives the selected text back to the narrator and removes its tags.
- **Speakers**: rename, choose the **voice** of each (from the voice list; "main voice" = the book's voice),
  add (up to 16 in all) or remove a speaker (their passages return to the narrator). With a Fish engine the
  bundled voices are marked with `*` and are refused (see [Fish Audio engines](fish-engines.md#voices-of-real-people)).
- **Expression tags** (a nested disclosure): put the cursor where the effect should happen and click a tag in the list (search by name
  or category). A tag at the very start of a passage is a delivery tag of that passage. Click a tag in the text to
  remove it. *Use expression tags* is the per-book switch.
- **Listen**: select a passage (up to 1500 characters, whole paragraphs are read) and press *Listen to the
  selection*; it is read with the speakers' voices and tags using the engine chosen in *3 · Reading engine*
  (a local one), without touching the audiobook.
- **Automatic markup**: see above; progress is saved and the editor reloads the result so you can correct it.
- **Voice ideas**: the *Voice ideas* button of a speaker writes three **English** voice descriptions from the
  character list (simple, standard, detailed: the simple one works with any voice-design model, the detailed one
  helps strong ones; a weak model ignores words it does not know). They never contain the character's name or a
  real person, and each character is asked to differ from the voices described before. Edit them, choose one,
  pick a generator (cloud providers that can design a voice in the book's language; the estimate and the
  "text is sent and billed" confirmation are shown) and make 3 takes that read one of the character's own
  lines. **You listen and choose**: no take is preferred automatically (speech recognition is not used), takes
  from several descriptions stay in the list, *Use for this speaker* adds the take to your voices and gives it
  to the speaker. In the console: `folivox markup voices BOOK` (add `-g qwen3-voicedesign` or a cloud provider to
  make takes into `BOOK.voices/`).
- **Save / Undo / Redo**: *Save* (Ctrl/Cmd+S) checks the markup against the book; Undo/Redo (Ctrl/Cmd+Z, with Shift
  to redo) cover every edit since the editor was opened. Closing with unsaved changes asks first.

Paragraphs that contain line breaks (poems) are shown but cannot be marked in the editor; the JSON can address
them. The same operations exist in the console (`folivox markup export` / `import`).

## Studio routes

The studio keeps the markup per book (`GET/PUT /api/books/{id}/markup`, `GET /api/markup/tags`) and uses it in
renders and previews (options `use_markup`, `expression_tags`). Automatic markup runs as a background task per
book: `POST /api/books/{id}/llm/start` (`{"task": "analyse" | "auto", "model", "llm", "chapters",
"expression_tags", "sample"}`), `GET .../llm/status`, `GET .../llm/estimate?chapter=N` (windows of a run), `POST .../llm/cancel`; the character list is
`GET/PUT /api/books/{id}/characters` and the model proposals `GET /api/llm/models`.
