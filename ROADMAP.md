# Roadmap: from prototype to the North Star

Every goal on this page carries an honest label:

- **[building]**: in progress now
- **[planned]**: achievable with today's science and engineering; scheduled
- **[research]**: needs scientific or engineering breakthroughs nobody has made yet; we aim at it and support the people working on it, but do not promise it
- **[beyond known physics]**: contradicts current physics as far as anyone knows; kept as an inspiration only

## The North Star

An AI built from scratch that reasons openly, respects every culture, never dominates or manipulates anyone, is decentralised and free forever, helps people grow, and, over the long term, helps humanity end disease and famine and become a space-faring society. See [CHARTER.md](CHARTER.md) for the values that govern it.

---

## Phase 1: Foundations and a working prototype [building]

Training hardware: Kaggle's free GPUs (two T4s). Model: option C, a ~25M-parameter model plus a cited library search ([docs/MODEL_OPTIONS.md](docs/MODEL_OPTIONS.md)).

| Milestone | What | Status |
|---|---|---|
| M0 | Charter (plain and machine-readable), governance, licences, data policy, docs, CI | done, awaiting review |
| M1 | Safety layer: consent gate, Charter Rules policy language, kill switch, audit log, integrity checks | next |
| M2 | Our own tokenizer, data pipeline, language coverage measurements | planned |
| M3 | Model, training, evaluation, checkpoints; CPU proof run; Kaggle run | planned |
| M4 | Safety evaluation suite and release gate | planned |
| M5 | Local, private assistant app (goals, reflection, cited library, chat through the safety layer) | planned |
| M6 | Decentralisation design, threat model and prototype (signed releases, peer-to-peer sharing, volunteer training simulation) | planned |
| M7 | Phase 1 wrap-up, v0.1 release, personal signing key for the founding maintainer | planned |

## Phase 2: Reach and resilience [planned]

- Assistant in the **browser and on phones**, running fully on-device (our own inference code; WebGPU where available).
- **Real volunteer training over the internet**: evaluate Hivemind hands-on (active, but mostly one maintainer); opt-in, capped, with energy shown to volunteers.
- Port the safety layer to **Rust** (a language that rules out whole classes of memory bugs) for a hardened, separately audited guardian.
- Larger models (~110M–350M parameters) using volunteer compute; instruction tuning on human-written open conversations.
- Grow to **at least 3 maintainers** from more than one organisation; multi-maintainer release signing.
- Independent security audit; reproducible builds; open-source legal review.
- Mirrors outside GitHub (for example Codeberg, peer-to-peer git) so no single host is a point of control.

## Phase 3: Many languages, many communities [planned]

- **Speech**: a from-scratch speech-recognition model trained on Mozilla Common Voice (CC0), so people can talk to the assistant in languages that are mostly spoken.
- **Community content packs**: local health resources, farming calendars, cultural context, all maintained by communities themselves and signed by them.
- Coverage targets measured in [docs/LANGUAGES.md](docs/LANGUAGES.md): raise every language with enough consented open text to L2–L3.
- Accessibility: screen readers, simple-language mode, low-literacy voice mode.
- Sign languages: [research], led by Deaf communities.

## Phase 4 and beyond: research directions [research]

- **Reasoning the model can show and check**: models whose reasoning steps can be verified, not just generated.
- **Interpretability**: understanding *why* a model says what it says.
- **Better ways to measure manipulation, deception and bias** in models too small or too large for today's tests.
- **Scaling up without centralising**: training much larger models across volunteers with no single point of control, robust to malicious participants. Today this is an open research problem.

---

## The North Star goals, honestly

### Ending disease
- **Near term [planned]:** help people navigate **open, cited medical knowledge** in their own language (the assistant explains and points to sources; it does **not** diagnose). Help people prepare questions for health workers. Connect volunteers to **distributed science** projects such as Folding@home and BOINC projects.
- **Long term [research]:** contributing to biomedical research tools, together with scientists. Ending disease is a vast scientific and social effort; an assistant can support it, not achieve it alone.

### Ending famine
- **Near term [planned]:** offline, community-reviewed **open agricultural knowledge packs** in local languages; connecting people with local food-sharing and volunteering.
- **Honest note:** modern famines are driven mainly by conflict, poverty and distribution, not lack of knowledge. Information helps; it is not enough on its own.

### Becoming space-faring
- **Near term [planned]:** open space-science learning paths (much NASA material is public domain); connecting volunteers with **citizen science** (for example Zooniverse) and open-source ground stations (for example SatNOGS).
- **Interstellar travel within a human lifetime [research]:** beyond current engineering. The nearest serious proposals are gram-scale probes pushed by lasers to a fraction of light speed, still at research stage. Crewed interstellar travel within a lifetime has no known feasible design.
- **Faster-than-light travel and teleportation of people or objects [beyond known physics]:** current physics does not allow them. ("Quantum teleportation" is real but transfers quantum states, not matter.)

### Communication no one profits from
- **Near term [planned]:** the assistant syncs between your own devices over your local network with **no server**; later, interoperate with open mesh networks (for example LoRa-based mesh radios) for places without internet.
- **Translation between languages [planned → research]:** grows with language coverage; reliable translation for low-resource languages is still a research problem.
- **Transportation no one profits from [research]:** outside this project's scope beyond supporting open engineering knowledge.

### Understanding all languages, on Earth and beyond
- See [docs/LANGUAGES.md](docs/LANGUAGES.md). Earth: [planned], measured per language. Animal communication: [research]. Extraterrestrial language: [research]; no data exists.

---

*This roadmap is updated at the end of every working session, together with [PROGRESS.md](PROGRESS.md).*
