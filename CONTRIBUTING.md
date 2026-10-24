# Contributing

Thank you for wanting to help. You do not need to be a programmer: some of the most valuable contributions are reviewing the charter, translating, checking data licences, and testing the app in your language and culture.

Everyone taking part agrees to the [Code of Conduct](CODE_OF_CONDUCT.md).

## Ways to help

- **Review the charter** ([CHARTER.md](CHARTER.md)). Does it protect people well? Is anything unclear, missing or culturally narrow? Open an issue.
- **Translate** the charter, docs or app interface. Translations made by machine or AI must be labelled as such and need review by a native speaker before they count as reviewed.
- **Check data sources** in [DATA.md](DATA.md) and `data/sources.toml`. Is the licence right? Is the source ethical? Should a community be consulted first?
- **Test** the software and report problems.
- **Write code**: see below.

## Rules every contribution follows

These come from the charter and [CLAUDE.md](CLAUDE.md) and apply to humans and AI tools alike:

1. **Honesty.** No placeholder presented as working. Label every stub, mock or simulation (`STUB`, `MOCK` or `SIMULATION` in the code, and in the docs). Never overstate what the software can do.
2. **Built from scratch.** No pretrained weights, no fine-tuning of existing models, no commercial AI APIs inside the product.
3. **No AI-generated text in training data**, including text written with AI assistants. Training data must be human-made and openly licensed, and listed in `data/sources.toml` with its licence.
4. **Safety layer stays separate.** Model code never gets write access or a way around the consent gate.
5. **Tests.** New code comes with tests, and all tests must pass. Never disable or skip a safety test.
6. **Protected areas** (charter, safety layer, release gate, licences, governance) need explicit human maintainer approval. See [GOVERNANCE.md](GOVERNANCE.md).

## Signing off your work (DCO)

We use the [Developer Certificate of Origin](https://developercertificate.org/) instead of a contributor licence agreement. You keep the copyright to your work, and nobody can ever re-license the project as proprietary. Add a sign-off line to each commit:

```bash
git commit -s -m "Describe your change"
```

This adds `Signed-off-by: Your Name <your@email>` and certifies that you have the right to submit the work under the project's licences.

An AI assistant cannot make that certification. For work written with an AI coding assistant (as much of the early code is), the human maintainer who reviews and merges it takes responsibility for it.

## Licences of contributions

- Code: [AGPL-3.0-or-later](LICENSE)
- Documentation, charter and model weights: [CC BY-SA 4.0](LICENSE-DOCS)

See [docs/LICENSING.md](docs/LICENSING.md) for why.

## Developer setup

You need Python 3.11 or newer.

```bash
git clone https://github.com/MarcGRusty/humanity-first-ai.git
cd humanity-first-ai
python -m venv .venv
source .venv/bin/activate        # on Windows: .venv\Scripts\activate
pip install -e ".[dev]"   # add ",train" for PyTorch (large download)
python -m pytest
```
