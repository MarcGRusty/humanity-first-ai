# Model options for Phase 1

**Decision (October 2026): Option C**, the default chosen at plan approval. The training hardware is Kaggle's free GPUs (two NVIDIA T4s, about 30 GPU-hours a week). All figures are **estimates** until a real run measures them; measured numbers will be added here.

All three options use the same Transformer code (see the [glossary](GLOSSARY.md)), so moving from one to another later needs no redesign.

| | A. Small model | B. Medium model | **C. Small model + library search (chosen)** |
|---|---|---|---|
| Size | ~25M parameters | ~110M parameters (about GPT-2-small size) | ~25M parameters, plus a search index |
| Training text | ~1B tokens | ~2.2B tokens | ~1B tokens, plus an offline library of open reference text |
| Kaggle GPU time | ~2–5 hours (one session) | ~15–40 hours (1–2 weeks of free quota, resumed across sessions) | ~2–5 hours, plus about 1 hour of CPU to build the index |
| Energy | ~0.3–1 kWh | ~2–6 kWh | ~0.3–1 kWh |
| What it can do | Mostly grammatical sentences; drifts off topic quickly; often wrong on facts | Fluent paragraphs; still weak on facts and reasoning | Finds relevant passages and **quotes them with sources**. The model's own wording is shown separately, labelled "AI draft, may be wrong". |
| Runs on | Any laptop | Most laptops | Any laptop |

## How the estimates were made

- Training compute is about **6 × parameters × tokens** arithmetic operations (a standard rule of thumb), plus roughly 20–30% for attention at these sizes.
- Two T4s were assumed to deliver about **10–30 trillion useful operations per second** in fp16. Small models rarely use a GPU fully, hence the wide range.
- Energy: two T4s draw at most 70 W each; the host machine roughly doubles that.

Example (option B): 6 × 110M × 2.2B ≈ 1.5 × 10¹⁸ operations ÷ (1–3 × 10¹³ per second) ≈ 14–40 hours.

## Why C

At this size the model cannot reliably remember facts. If facts come from cited passages that the person can read, the assistant is useful *and* honest, while the model's own fluency improves over time. The design upgrades cleanly: swap in a larger model (B, or bigger with volunteer compute) without changing the rest.

## What none of these can do

None of these models will "reason for itself" in the human sense, hold a real conversation over many turns, or be reliable on facts without sources. Those are research goals for later phases, tracked in [ROADMAP.md](../ROADMAP.md).
