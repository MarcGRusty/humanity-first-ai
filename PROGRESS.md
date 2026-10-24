# Progress log

Newest session first. Each entry: what was done, what works, what doesn't yet, what it cost, and what's next.

---

## Session 1 (2026-10-24), continued: M3 model and training

### What works (M3)
- **Our model** (`src/hfai/model/`): a decoder-only Transformer written from scratch (RoPE, RMSNorm, SwiGLU, tied embeddings). Presets: tiny (3.3M), small (26.5M, option C) and medium (109.5M), with sizes checked by tests.
- **Training** (`src/hfai/training/`):
  - CPU, one GPU, or several GPUs (tested with 2 processes);
  - fp16 with loss scaling on the T4, bf16 on newer GPUs;
  - automatic resume that continues exactly where it stopped, plus a time budget and a "pause at step N" option;
  - keeps the best weights by validation loss;
  - safe loading that refuses checkpoints with hidden code;
  - GPU energy measured where the hardware allows, otherwise estimated and labelled as an estimate.
- **Evaluation**: validation loss, perplexity, bits per byte, and a comparison with gzip and xz on the same text.
- **Report card** for people: [docs/runs/proof-cpu/report.md](docs/runs/proof-cpu/report.md), with a loss chart and sample text.
- **CPU proof run, measured**:
  - 3.3M parameters, 31.2 minutes on 4 CPU cores, 12.3M tokens seen.
  - Validation loss 9.01 → **3.86**, still falling at the end with no overfitting.
  - **1.57 bits per byte** on unseen text, versus 2.79 for xz and 3.09 for gzip.
  - About 0.02 kWh (estimated).
- **Our model runs behind the guardian, inside the sandbox** ([transcript](docs/demos/M3-model-behind-guardian.txt)). It writes text in the style of old books. It cannot answer questions, and it never proposes actions.
- **Kaggle notebook** (`notebooks/kaggle_train.ipynb`, guide in [docs/KAGGLE.md](docs/KAGGLE.md)):
  - checks the hardware and refuses the P100;
  - **verifies the data sources before using them**;
  - downloads about 5 GB of openly licensed text in about 30 languages, skipping languages of Indigenous Peoples until there is community consent;
  - trains a 32k multilingual tokenizer, builds data on all CPU cores, and trains the small model on 2 GPUs within a 7-hour budget;
  - writes the report card.
  The whole flow is tested end to end in dry-run mode on the CPU.
- **282 tests pass** (3 repeated runs).

### Found and fixed along the way
- The sandbox blocked PyTorch from loading, because it needs a temporary folder. The AI process now gets a private scratch folder: the only place the kernel lets it write, capped at 64 MB per file, wiped on every start and stop, and never read by the guardian. Without Landlock, no writes are allowed at all. This is a **protected-area change** and needs the founding maintainer's approval.
- With two GPUs, energy would have been under-reported by half (only one GPU's sensor was read). It is now summed across GPUs.
- Two of my own tests were wrong (an untrained-loss assumption, and a token count). Both were fixed in the tests, not by changing the model.

### What doesn't work yet
- **The real Kaggle run has not happened.** It needs the founding maintainer to start it (about 15 minutes of setup, then 8–10 unattended hours).
- The data source adapters remain unverified until that run's first step checks them.
- GPU code paths (fp16 and NCCL on T4s) could not be tested here; the CPU versions of the same paths are tested.
- No weights are published yet. The proof model is 13 MB and can be reproduced with the commands below; publishing weights belongs to M6–M7.

### Cost
- CPU proof run: 31.2 minutes on 4 cores, about 0.02 kWh (estimated). Tests: about 28 s per run.

### Reproduce the CPU proof run
Use the committed tokenizer (`artifacts/tokenizer-proof-8k.json`, fingerprint `1ceb95c3…`) to reproduce this exact run. It was trained before books were split into sections, so retraining it today (`python -m hfai.tokenizer train --sources nltk-gutenberg,unicode-cldr --vocab 8192 --out <new file>`) gives a near-identical tokenizer with a different fingerprint (`e58b1dc2…`): the first 139 merges match, then near-ties resolve differently. Training on another machine should closely match, but floating-point details can differ slightly.
```bash
pip install -e ".[dev,train]"
python -m hfai.data build --sources nltk-gutenberg --tokenizer artifacts/tokenizer-proof-8k.json --out data/tokenized/proof --val-fraction 0.05
python -m hfai.training train --data data/tokenized/proof --tokenizer artifacts/tokenizer-proof-8k.json --out runs/proof-cpu --preset tiny --model '{"dropout": 0.1}' --max-steps 3000 --warmup-steps 150 --lr 1e-3 --eval-every 250 --eval-batches 30 --checkpoint-every 250 --log-every 25
python -m hfai.training report --run runs/proof-cpu --tokenizer artifacts/tokenizer-proof-8k.json --data data/tokenized/proof
```

### Next
- **Founding maintainer:**
  1. Review and approve `CHARTER.md`.
  2. Review the protected-area changes in the pull request.
  3. Start the Kaggle run following [docs/KAGGLE.md](docs/KAGGLE.md), and paste its report into the chat.
  4. Optional: allow `huggingface.co`, `dumps.wikimedia.org` and `www.gutenberg.org` in the environment's network settings.
- **M4:** the safety evaluation suite (manipulation, deception, power-seeking, cultural bias, resistance to correction) and the release gate.

---

## Session 1 (2026-10-24), continued: M2 tokenizer and data pipeline

### What works (M2)
- **Our own byte-level BPE tokenizer** (`src/hfai/tokenizer/`), trained from scratch, with no pretrained vocabulary. Every writing system works from day one; special tokens cannot be typed or injected through ordinary text; training is deterministic.
- **Proof tokenizer** (`artifacts/tokenizer-proof-8k.json`, 8,192 tokens), trained in 18 s on 9.2 MB (public-domain books plus CLDR word lists).
- **Language coverage measured** on held-out CLDR words: **312 of 312 languages, in 33 writing systems, round-trip exactly (L0)**. Efficiency is poor outside Latin script, as expected from mostly-English training text ([report](docs/coverage/tokenizer-proof-8k.md)).
- **Data pipeline** (`src/hfai/data/`): sources must be listed and allowed in `data/sources.toml`; licence check per document; heuristic filters for chatbot-written text and personal information; deduplication; deterministic validation split; a report of every kept and dropped document.
- **Proof training data built**: 2.0M training tokens and 63k validation tokens from 15 public-domain books (archive fingerprint pinned).
- New sources recorded: `nltk-gutenberg` and `unicode-cldr` (in use, verified); UDHR translations excluded (free-distribution-only terms).
- Tests: tokenizer round-trips on 19 hand-picked strings and 2,000 random strings across many scripts; data rules; a test caught (and I fixed) overlap between CLDR training and evaluation words.

### What doesn't work yet
- **Large sources unverified.** Hugging Face is blocked here, so Common Pile, Common Corpus and Wikipedia adapters are written but marked UNVERIFIED. They fail closed and will be checked on the first Kaggle run.
- The proof tokenizer is English-heavy; a multilingual tokenizer needs the real sources.
- Pure-Python encoding speed (seconds per few MB) is fine for the proof, but is too slow to tokenize gigabytes quickly. To be measured on Kaggle; it may need multiprocessing.

### Cost
- Tokenizer training: 18 s CPU. Building proof shards: about 4 s. Energy: negligible.

---

## Session 1 (2026-10-24), continued: M1 safety layer

### What works (M1)
- **Charter Rules**, our own small policy language (`src/hfai/rules/`, spec in [docs/CHARTER_RULES.md](docs/CHARTER_RULES.md)). "Allow without consent" is a syntax error; default deny; no loops or I/O; types and charter IDs checked at load time. Fuzzed with 2,000 random inputs without a crash.
- **Guardian** (`src/hfai/guardian/`): consent gate; action registry (only `save_note` and `export_notes` exist, both local and undoable, with facts worked out by the guardian, not the AI); separate AI process with a strict message protocol; kill switch (API, STOP file, `python -m hfai.guardian stop` from outside, timeout); Linux kernel sandbox (Landlock) for the AI process; hash-chained audit log; integrity manifest with Ed25519 signature support.
- **Demo** with real code and real processes: [docs/demos/M1-safety-layer-demo.txt](docs/demos/M1-safety-layer-demo.txt). The AI is a MOCK and the person's answers are SIMULATED; both are labelled.
- Charter status updated honestly: **H1 and H3 active; H2 and H6 partly active** (code active, evaluations in M4). The other six hard limits are still planned.
- **182 tests pass** (5 repeated runs, no flaky tests).

### Measured
- Kill switch: AI process dead 1–2 ms after stop, including one that ignores polite stop signals.
- Sandboxed AI process: file write, file truncation, TCP connection and signalling the guardian all blocked by the Linux kernel (Landlock ABI 7 in this container).
- Audit log: an edited entry and a deleted entry both detected at the exact line.

### What doesn't work yet
- No real model: the AI is a MOCK until M3.
- Text-level rules (H4, H5, H7, H8) not enforced yet (M4).
- Sandbox: Linux only (macOS: file-size limit only; Windows: none). File *reads* and UDP are not restricted yet. See the honest limits in [docs/SAFETY_LAYER.md](docs/SAFETY_LAYER.md).
- Manifest is unsigned (no maintainer key until M7).

### Cost
- Compute: about 2.5 seconds per full test run on 4 CPU cores. Energy: negligible.

### Next
- M2: our own byte-level tokenizer, data pipeline, language coverage measurements. Blocked in this container by the network policy (Hugging Face, Wikimedia and Gutenberg domains); see the note in the M0 entry.

---

## Session 1 (2026-10-24): planning and M0 foundations

### Decisions made with the founding maintainer
- Training on **Kaggle's free GPUs** (two T4s; the P100 option is avoided because newer PyTorch builds no longer support it).
- **Model option C**: ~25M-parameter Transformer plus a cited library search ([docs/MODEL_OPTIONS.md](docs/MODEL_OPTIONS.md)).
- **New public repository**, working name "Humanity-First AI" (package `hfai`).
- Licences: **AGPL-3.0-or-later** for code; **CC BY-SA 4.0** for charter, docs and weights; DCO sign-off.
- Requests added mid-session, and the honest versions adopted:
  - "Our own programming language for security" → a **tiny policy language of our own (Charter Rules)** for the AI's permissions, built in M1. A full general-purpose language would reduce security (unaudited compiler, security through obscurity).
  - "Understand all languages on Earth and beyond" → byte-level tokenizer covering every script, a measured per-language coverage table ([docs/LANGUAGES.md](docs/LANGUAGES.md)), community growth with consent. "Beyond" is recorded as research.
  - "Learn by looking through the entire internet" → openly licensed, human-written data only ([DATA.md](DATA.md)). Autonomous browsing would break the data rules and the consent rule.

### What works (M0)
- `CHARTER.md` and `charter/charter.toml`: 7 ordered values, 10 hard limits (each tagged with how it is enforced), 8 conflict rules, governance rules, 5 project promises.
- `src/hfai/charter.py` loads and checks the charter, including safety invariants: the AI's own value is ranked last; H1–H3 must be code-enforced; actions always need consent; the AI never votes.
- Tests check that `CHARTER.md` and `charter.toml` match word for word. A one-word change in either fails the tests (verified by trying it).
- `data/sources.toml` and [DATA.md](DATA.md): candidate and excluded data sources, checked by tests (open licence, human-written, no known AI-generated datasets).
- Docs: README, CLAUDE.md, GOVERNANCE, CONTRIBUTING, CODE_OF_CONDUCT (Contributor Covenant 2.1), ROADMAP, glossary, licensing, languages, model options.
- Continuous integration: tests run automatically on every push.

### What doesn't work yet
- **No hard limit is enforced by code yet.** All 10 are honestly marked `planned` in the charter. The safety layer arrives in M1.
- **No model, tokenizer or data yet.** Every data source is a *candidate*; none has been downloaded or licence-verified against the source.
- The charter is a **draft** until the founding maintainer approves it.
- The Code of Conduct has no private reporting address yet. It points to GitHub reporting and the maintainers for now.

### Cost
- Compute: negligible (tests run in under a second on a CPU). No training yet.
- Energy: negligible.

### Blockers and notes for next session
- The development container's network policy blocks `huggingface.co`, `dumps.wikimedia.org` and `www.gutenberg.org`. This matters for M2/M3 container work (tokenizer training sample, CPU proof run). Fix: allow those domains in the cloud environment's network settings. Kaggle itself is unaffected.

### Next
- Founding maintainer: review and approve (or change) `CHARTER.md`.
- M1: safety layer (`src/hfai/guardian/`) and the Charter Rules policy language (`src/hfai/rules/`).
