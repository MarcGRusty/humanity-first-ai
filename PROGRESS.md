# Progress log

Newest session first. Each entry: what was done, what works, what doesn't yet, what it cost, and what's next.

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
