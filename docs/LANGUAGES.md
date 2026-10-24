# Languages: understanding and being understood

**Goal:** the AI should understand, and be understood by, people in every language on Earth, and, as a far research aspiration, beyond.

**Honest starting point:** there are about 7,000 living languages. Many are mainly spoken or signed and have little written text; many are endangered. Today even the largest commercial AI systems work well in only a few hundred. A small model trained from scratch on open data will start out useful in very few languages. This page tracks real coverage, language by language, so nobody has to guess.

## Coverage levels

| Level | Meaning | How it is measured |
|---|---|---|
| **L0 Encodable** | Text in this language's script can be stored, displayed and processed without loss | Tokenizer round-trip test: text goes in, comes back identical (M2) |
| **L1 Interface** | The app's buttons and messages are translated | Translation file exists. Marked *draft* until a native speaker reviews it |
| **L2 Seen** | The model has trained on some text in this language | Token counts per language in the training data (M2–M3) |
| **L3 Basic** | The model's text in this language is mostly understandable | Measured prediction quality on held-out text, then spot checks by speakers |
| **L4 Good** | Native speakers rate the assistant as useful in this language | Human evaluation by community members |

## Current coverage (M2, measured)

| Level | Languages | Evidence |
|---|---|---|
| **L0 Encodable** | **all 312 languages tested, in 33 writing systems** | Every one round-trips exactly through our tokenizer ([report](coverage/tokenizer-proof-8k.md)). Because the tokenizer works on bytes, any other Unicode text does too; random text from 15 Unicode ranges is tested on every change |
| L1 Interface | none yet | The app arrives in M5 |
| L2 Seen | English only | The CPU proof model (M3) read only public-domain English books. The Kaggle run will add about 30 languages |
| L3, L4 | none | |

**How efficiently each language is encoded** (characters per token, higher is better) is in the [proof tokenizer report](coverage/tokenizer-proof-8k.md). Honestly: the proof tokenizer learned mostly from English books, so Latin-script languages get about 1.7 characters per token while Chinese, Japanese, Korean, Ethiopic and Canadian Aboriginal syllabics get below 1, meaning they are spelled out almost byte by byte. The tokenizer for the real Kaggle run will be trained on multilingual text (Wikipedia in many languages, Common Corpus) and measured the same way.

## How coverage grows

- **Every script from day one (L0):** the tokenizer works on raw bytes, so no language is "unknown" to it.
- **Interface (L1):** translation files that communities can edit. Translations drafted by AI tools are labelled *draft, needs native-speaker review* and are never used as training data.
- **Model (L2–L4):** more open, human-written text per language: Wikipedia, open books, and **community-contributed text given with consent**. Indigenous-language data follows the CARE principles (see [DATA.md](../DATA.md)).
- **Speech (Phase 3):** many languages are mostly spoken. [Mozilla Common Voice](https://commonvoice.mozilla.org/) (CC0, 100+ languages) makes a from-scratch speech model possible.
- **Sign languages (research):** need video understanding, and must be led by Deaf communities.

## "Beyond": research aspirations, not features

- **Animal communication:** serious early-stage research exists (for example on sperm whale vocalisations). Finding structure in animal sounds is not the same as understanding a language. Our realistic role is to follow and support open research.
- **Extraterrestrial communication:** no extraterrestrial language is known, so there is nothing to learn from. Decoding an unknown language with no shared reference is an unsolved problem. Science-based message design (mathematics and physics as common ground) is a real field and a fitting long-term interest.
