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

## Studio

The studio keeps the markup per book (`GET/PUT /api/books/{id}/markup`, `GET /api/markup/tags`) and uses it in
renders and previews (options `use_markup`, `expression_tags`). The visual editor is described in the studio
documentation.
