# Humanity-First AI *(working name)*

An open, original AI that puts people first. It is:

- **Built from scratch.** Our own code, tokenizer and weights. No pretrained models, no commercial AI services, no AI-generated training data.
- **Governed by a public charter.** [CHARTER.md](CHARTER.md) sets out its values (human safety and freedom first), the hard limits it must never cross, and how only humans can change them.
- **Safe by design.** The AI may think freely, but a separate safety layer holds the only key to actions, and every action needs your consent. There is a kill switch that always works on your device and a tamper-evident log of everything it does.
- **Private and local-first.** It runs on your own device, with no account, ads or tracking. Your data stays with you unless you choose otherwise.
- **For people's growth, not screen time.** It helps with your own goals (health, learning, relationships, purpose, helping others) and never optimises for engagement.
- **Free forever, owned by no one.** Open licences, peer-to-peer distribution, community governance, and no tokens or paid tiers.

## Status: early prototype (Phase 1, milestone M2)

Honestly, today:

| Part | Status |
|---|---|
| Charter (plain language + machine-readable, kept in sync by tests) | ✅ Draft, awaiting founding maintainer approval |
| Governance, licences, data policy, docs | ✅ Done |
| Safety layer: consent gate, kill switch, sandboxed AI process, audit log, integrity checks, our own Charter Rules policy language | ✅ Working and tested with a MOCK AI ([docs/SAFETY_LAYER.md](docs/SAFETY_LAYER.md)) |
| Our own tokenizer (all 312 tested languages round-trip) and a licence-tracking data pipeline | ✅ Working; large data sources not yet verified ([docs/LANGUAGES.md](docs/LANGUAGES.md)) |
| Model and training | ⏳ Next (M3), **no trained model exists yet** |
| Safety evaluations and release gate | ⏳ Planned (M4) |
| Assistant app | ⏳ Planned (M5) |
| Peer-to-peer distribution and volunteer training | ⏳ Planned (M6) |

What to expect when the model exists: it will be **small** (about 25 million parameters, trained on free GPUs). It will write simple text and find and quote passages from an open library, with sources. **It will not "think for itself" or be reliable on facts without sources.** Those are long-term research goals. Details in [docs/MODEL_OPTIONS.md](docs/MODEL_OPTIONS.md) and [ROADMAP.md](ROADMAP.md).

## Read more

- [CHARTER.md](CHARTER.md): the AI's constitution
- [ROADMAP.md](ROADMAP.md): from this prototype to the long-term vision, with honest labels
- [PROGRESS.md](PROGRESS.md): what has been done, session by session
- [DATA.md](DATA.md): every data source and its licence
- [docs/LANGUAGES.md](docs/LANGUAGES.md): language coverage, measured
- [docs/SAFETY_LAYER.md](docs/SAFETY_LAYER.md): how the safety layer works, measured results, honest limits
- [docs/CHARTER_RULES.md](docs/CHARTER_RULES.md): our own small policy language
- [docs/GLOSSARY.md](docs/GLOSSARY.md): plain-language explanations of the technical terms
- [GOVERNANCE.md](GOVERNANCE.md): how decisions are made
- [CONTRIBUTING.md](CONTRIBUTING.md): how to help, including without coding

## Try the checks yourself

You need Python 3.11 or newer.

```bash
git clone https://github.com/MarcGRusty/humanity-first-ai.git
cd humanity-first-ai
python -m venv .venv
source .venv/bin/activate        # on Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python -m pytest                 # run all tests
python -m hfai.charter           # check the charter and print a summary
python -m hfai.guardian demo     # watch every safeguard work (MOCK AI, simulated answers)
```

## Licence

Code: [AGPL-3.0-or-later](LICENSE). Charter, documentation and model weights: [CC BY-SA 4.0](LICENSE-DOCS). Why: [docs/LICENSING.md](docs/LICENSING.md).
