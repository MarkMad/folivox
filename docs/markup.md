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
fits (`gemma4:31b-it-qat` from 48 GB, `26b-a4b-it-qat` from 32 GB, `12b-it-qat` from 16 GB, `e4b`, `e2b`) and
you can use any other Ollama model, or an OpenAI-compatible API (`--llm openai --model NAME`, your key, the text
goes to that service). Set a default in `config.toml`: `[llm.ollama] model = "gemma4:12b-it-qat"`. The analysis
runs before the audio is made, never together with the voice model. Small models miss subtle speakers: check
the result.

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

## Studio

The studio keeps the markup per book (`GET/PUT /api/books/{id}/markup`, `GET /api/markup/tags`) and uses it in
renders and previews (options `use_markup`, `expression_tags`). Automatic markup runs as a background task per
book: `POST /api/books/{id}/llm/start` (`{"task": "analyse" | "auto", "model", "llm", "chapters",
"expression_tags", "sample"}`), `GET .../llm/status`, `POST .../llm/cancel`; the character list is
`GET/PUT /api/books/{id}/characters` and the model proposals `GET /api/llm/models`.
