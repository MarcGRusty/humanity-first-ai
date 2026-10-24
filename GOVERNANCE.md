# Governance

How this project makes decisions, who can make them, and how the charter changes. The aim: **no company, person or server controls the project** (promise P5), while still keeping a clear, accountable process.

## Where we are today (honestly)

The project has **one maintainer**: MarcGRusty, the founding maintainer. One person is a single point of control, which is exactly what P5 says to avoid. This document therefore includes **bootstrap protections** that limit what a small group can do, and growing the maintainer group is a Phase 1–2 goal (see [ROADMAP.md](ROADMAP.md)).

AI coding assistants (such as Claude) help build the project. **They are tools, not maintainers:** they may draft changes, but every merge and every decision is made by a human. They have no vote (charter, `governance.ai_may_vote = false`).

## Roles

- **Contributors**: anyone who opens an issue, reviews, translates, tests or submits a change. No permission needed.
- **Maintainers**: contributors trusted to review and merge changes and to sign releases. Listed below.
- **Founding maintainer**: MarcGRusty. Has no special powers beyond those of any maintainer once there are three or more maintainers.

### Current maintainers

| Maintainer | Since | Areas |
|---|---|---|
| MarcGRusty | 2026 | Everything (founding maintainer) |

## Ordinary decisions

Most changes (code, docs, tests) follow **lazy consensus**: a maintainer reviews and merges a pull request if the tests pass and nobody raises a reasoned objection. Disagreements are discussed in the open, in the issue or pull request. If they cannot be settled, maintainers vote by simple majority.

## Protected areas

Changes to these need explicit approval from a human maintainer who did not write the change (while there is only one maintainer: explicit approval from that maintainer, recorded in the pull request), and must say "PROTECTED AREA" in the pull request description:

- `CHARTER.md` and `charter/` (also follow the charter change process below)
- `src/hfai/charter.py`, `src/hfai/guardian/`, `src/hfai/rules/` (the safety layer)
- the evaluation suite's release gate
- licences (`LICENSE`, `LICENSE-DOCS`, `docs/LICENSING.md`)
- this file

The automatic tests must pass. Nobody, including maintainers, may disable or skip a safety test to get a change merged.

## Changing the charter

Summary from [CHARTER.md](CHARTER.md) Part 5, with the process in full:

1. **Propose in public.** Open an issue titled `Charter Change Proposal: <short title>` with the exact wording to change, in both `CHARTER.md` and `charter/charter.toml`, and the reasons.
2. **Comment period.** At least **30 days** for changes that add or strengthen protections. At least **90 days** for anything that weakens or removes a hard limit, or reorders the values.
3. **Approval.** At least two thirds of maintainers to strengthen. **Every** maintainer to weaken.
4. **Bootstrap protection.** While there are fewer than **3** maintainers, hard limits may be added or strengthened but **never weakened or removed**, and values may not be reordered.
5. **Safety evaluations** must pass with the changed charter.
6. **Merge** both files in one change, and record the new charter version and its fingerprint (`python -m hfai.charter`) in [PROGRESS.md](PROGRESS.md).

Fixing typos or clarifying wording without changing meaning: a 7-day comment period and one maintainer's approval. If anyone argues the meaning changes, the full process applies.

Updating a hard limit's **status** (planned, partly active, active) is not a charter change: it records a fact about the software, and is reviewed as part of the code change that makes it true. A status may only move toward "active" when working, tested enforcement is merged, and must move back if that enforcement is removed or found not to work.

## Releases

- An official release is a set of files (code, charter, weights) listed in a **signed release manifest**: each file's fingerprint (SHA-256), signed with maintainers' keys.
- Goal: releases need signatures from at least two thirds of maintainers. **Today, with one maintainer, releases are signed by one key and labelled "single-maintainer release".** Until the founding maintainer has created a personal signing key (a guided step in milestone M7), only a clearly labelled **development key** exists, and nothing signed with it is an official release.
- No release ships unless the release gate in the evaluation suite passes.
- **Security advisories** (for example "do not use weights version X") are signed the same way. Clients show them to the user. Nobody can remotely switch off anyone's copy.

## Becoming a maintainer

Any maintainer may nominate a contributor who has made sustained, careful contributions. Nomination is public; existing maintainers approve by two-thirds majority after 14 days. To avoid capture by any single organisation, **no more than one third of maintainers may share an employer or funder** (once there are three or more).

Maintainers may step down at any time. A maintainer who breaks the Code of Conduct or acts against the charter may be removed by a two-thirds vote of the other maintainers.

## Money

- The project never charges for access, never sells tiers, and never issues tokens (promise P1).
- Donations, if ever accepted, go through a transparent non-profit fiscal host with public accounts. They can never buy decisions, priority, access or influence over the charter.
- Maintainers declare any conflict of interest in the issue where it matters, and step back from that decision.

## Forks

Anyone may fork the project under its licences. Forks are welcome. A fork that removes or weakens the charter's protections should not present itself as an official release of this project.

## Changing this document

This file is a protected area. Changes follow the same process as strengthening the charter: a 30-day public comment period and two-thirds maintainer approval. The bootstrap protection also applies: while there are fewer than 3 maintainers, changes may not weaken the charter change process.
