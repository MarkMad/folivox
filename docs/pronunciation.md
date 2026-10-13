# Custom pronunciations

Names of characters and places, invented words, foreign terms: a text-to-speech model guesses how to read them
and is often wrong. A pronunciation dictionary tells it how, once for the whole book.

## The file

A plain-text file next to the book, in UTF-8:

- `book.pronounce.txt` for the book `book.epub`;
- `pronounce.txt` in the same folder for a whole series. The book's own file wins where both have the word.

One entry per line, `word = how to read it`. `#` starts a comment. Matching is by whole word, ignoring case.

```
# respelling: works with every engine
Kvothe      = Quothe
Eld'rin     = EL-drin

# stress: + before the stressed vowel, or ' right after it
Mirandel    = Mir+andel

# * keeps any ending: Tolkien's, Tolkiens
Tolkien*    = Tolkeen

# phonemes for the local engine | respelling for the online ones
Kvothe      = /K W OW1 TH/ | Quothe

# Russian: the same marks
замок       = зам+ок
```

In the studio the same text is edited under **Pronunciations** in the book details; it is saved by itself.
On the command line the file is found automatically; `--pronounce FILE` uses another one (repeat the option for
several files, a later file overrides an earlier one).

## Forms of a word

Enter every form yourself (`замок`, `замка`, `замку`). Stress often moves between forms, and no program can guess
the forms of an invented name. A `*` at the end of the word is a shortcut for names whose stem does not change
(`Фолиокс*` covers `Фолиокса`, `Фолиоксом`). An exact entry always beats a `*` one. In English the possessive
`'s` needs no entry: `Kvothe` also covers `Kvothe's`.

## What to write on the right

| Form | Example | Works with |
|---|---|---|
| Respelling | `Kvothe = Quothe` | every engine |
| Stress | `Mir+andel`, `зам+ок` | the local engine; online engines read the plain word |
| Phonemes | `/K W OW1 TH/` | the local engine only |
| Phonemes with a fallback | `/K W OW1 TH/ \| Quothe` | phonemes locally, the respelling elsewhere |

**Stress.** Put `+` before the stressed vowel (`Mir+andel`) or `'` right after it (`Mira'ndel`); `´` after the vowel
works too. Both forms are turned into what the local model follows: an apostrophe after the vowel in a Latin word, a
combining acute (U+0301) in a Cyrillic one. In our listening tests an apostrophe right after the stressed vowel (`Mi'randel`) moved the stress of an English
name, while an apostrophe after the whole syllable (`Miran'del`) did not and sometimes doubled a syllable
(`Thalas'sar` → "Thalassassar"), so do not use it. Russian takes the same marks (`зам+ок`, `замо'к`) and also one
capital vowel (`замОк`). Online engines would read a mark aloud, so they get the word without it. The model does not
always follow a mark: listen before rendering the whole book.

**Phonemes** are CMU/ARPAbet symbols separated by spaces: consonants `B CH D DH F G HH JH K L M N NG P R S SH T TH V
W Y Z ZH`, vowels `AA AE AH AO AW AY EH ER EY IH IY OW OY UH UW` with a stress digit (`1` primary, `2` secondary,
`0` none). CosyVoice 3 has tokens for them. In our tests `[K][W][OW1][TH]` was read as "Quoth", but a symbol is
sometimes dropped (the `V` of `K V OW1 TH`), so treat phonemes as a fine-tuning tool and check by ear. With an
online engine and no respelling after `|`, the word is read as written and a warning is shown.

## Finding the names

```bash
folivox names book.epub            # print the names: capitalised words that are not ordinary words
folivox names book.epub --write    # add the new ones to book.pronounce.txt
```

Every line comes out as `Name = Name   # 12x` (the number of occurrences): replace the right-hand side with how
to read it. Words already in the file are skipped. `--min N` and `--limit N` change the thresholds. Not for Chinese,
Japanese and Korean, which have no capitals.

## Trying it

In the studio, **Try it by ear** sits right under the list. The text field shows exactly what will be read:

- **Pick sentences from my book** fills it with sentences of the book that contain the first entries of your list,
  in the order of the list. A word the book never uses is read on its own, and the studio says which ones.
- Or type any sentence of your own.
- **▶ Listen** reads that text with your pronunciations, with the voice and engine chosen below. It takes about
  half a minute and is not added to the audiobook (an online engine bills this small test). With an empty field
  it picks the sentences first.

On the command line the dictionary applies to previews: `folivox book.epub --preview 400 -c 1`.
After a change only the fragments whose text changed are read again; everything else stays in the cache.

Quality control compares the recording with the respelled text, never with phoneme markup, so a respelling does
not cause pointless retakes.

## Limits

- An entry works inside one fragment; a multi-word entry (`Mount Doom = Mownt Doom`) does not match across a
  sentence boundary.
- Entries are replaced in one pass: `A = B` and `B = C` do not chain.
- Errors in a line (a missing `=`, an unknown phoneme) are shown as warnings and that line is skipped; the render
  does not stop.
