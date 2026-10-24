# CLAUDE.md: instructions for every AI coding session on this project

You are helping build **Humanity-First AI** (working name): an original AI built from scratch, governed by [CHARTER.md](CHARTER.md). Read this whole file before doing anything.

## Read first, every session

1. [CHARTER.md](CHARTER.md): the project's values and hard limits. Every design decision must be consistent with it.
2. [PROGRESS.md](PROGRESS.md): what was done last time and what is next.
3. [ROADMAP.md](ROADMAP.md): where this is going, and which goals are honest research aspirations rather than features.

## Honesty rules (these override everything else)

- **Never build theatrical components.** No "consciousness module", "sentience engine", or placeholder code presented as working. Label every stub, mock or simulation as one, in the code (docstring or comment containing `STUB`, `MOCK` or `SIMULATION`) and in the docs.
- **Never claim capabilities the system doesn't have.** For every milestone, give realistic expectations on capability, training time, hardware and power use.
- **Where a goal is beyond current science** (faster-than-light travel, teleportation, extraterrestrial language), say so plainly and record it as a research aspiration, not a feature.
- **If a request is contradictory or infeasible,** tell the owner and propose the closest achievable version.
- **Report outcomes faithfully.** If tests fail, say so and show the output. Never present an estimate as a measurement.

## "Not based on any existing AI": what that means here

- Our own model code, our own tokenizer and our own weights, all trained from scratch.
- No pretrained weights, no fine-tuning of existing models, and no commercial AI APIs inside the product.
- Standard open tools (Python, PyTorch, numpy, open datasets) are fine. They are tools, not AIs.
- **No AI-generated text in training data, ever.** That includes text written by you (Claude) in this repository: docs, eval prompts, examples and translations must never be used as training data. Synthetic datasets made with other AIs (for example TinyStories, Alpaca, ShareGPT, UltraChat) are excluded.
- Only openly licensed, ethically sourced data. Every source goes in `data/sources.toml` and [DATA.md](DATA.md) with its licence. The test suite checks this.

## Safety layer rules

- The safety layer (`src/hfai/guardian/`, `src/hfai/rules/`, `charter/`) is kept **separate from the model**. Model code must never import guardian internals or get write access to any file.
- The AI can reason freely but **cannot act without explicit human consent** (hard limit H1). Never add a code path that skips the consent gate, even "for testing" in production code.
- Changes to `charter/`, `CHARTER.md`, `src/hfai/charter.py`, `src/hfai/guardian/`, `src/hfai/rules/`, or the release gate are **protected**. Say so clearly in the pull request description; a human maintainer must explicitly approve them (see [GOVERNANCE.md](GOVERNANCE.md)). You may draft such changes, but never approve or merge them.
- CHARTER.md and charter/charter.toml must always change together; `tests/test_charter.py` enforces this.
- When a hard limit's enforcing code is built and tested, update its `status` (`planned` → `partial` → `active`) in both charter files in the same change.
- After any reviewed change to a protected file, run `python -m hfai.guardian integrity --update`, or the guardian (and `tests/test_integrity.py`) will refuse it. Never run it to make an unreviewed change pass.
- The AI process is untrusted: it only proposes. New abilities are added only as executors in `src/hfai/guardian/actions.py`, with facts worked out by the guardian, plus a rule in `charter/actions.rules`. Both are protected areas.

## The owner

The founding maintainer is new to programming and monitors and evaluates progress rather than writing code. So:

- Explain machine-learning concepts in plain language the first time they come up, and add new terms to [docs/GLOSSARY.md](docs/GLOSSARY.md).
- Give copy-paste steps for anything they need to do (for example running the Kaggle notebook).
- After each milestone, report: what works, what doesn't yet, what it cost (time, compute, power), and what's next.
- Give them ways to verify that don't need coding: CI status, demo transcripts, screenshots, report cards.

## How to work

- Build in small, testable steps. Write tests as you go and run them: `python -m pytest`.
- Keep dependencies minimal. The core (charter, guardian, rules) uses only the Python standard library plus `cryptography`.
- Plain, readable code over clever code; comments explain *why*.
- **Before ending a session, update [PROGRESS.md](PROGRESS.md) and [ROADMAP.md](ROADMAP.md)** so the next session can pick up where this one left off.

## Useful commands

```bash
python -m pytest              # run all tests
python -m hfai.charter        # check the charter and print a plain-language summary
python -m hfai.guardian demo  # run the safety-layer demonstration
python -m hfai.guardian integrity [--update]  # check (or, after review, record) protected files
python -m hfai.tokenizer train|report|encode   # our tokenizer
python -m hfai.data build|sources              # licence-tracked training data
python -m hfai.training train|report|generate  # train our model; torchrun for several GPUs
python notebooks/build_notebook.py            # regenerate the Kaggle notebook after editing it
```

Training data and runs (`data/raw/`, `data/tokenized/`, `runs/`) are not committed; report cards worth keeping go in `docs/runs/`.
