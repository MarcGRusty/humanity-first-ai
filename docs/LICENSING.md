# Licensing: keeping this free forever

## What we use

| What | Licence | File |
|---|---|---|
| Code | **GNU AGPL-3.0-or-later** | [LICENSE](../LICENSE) |
| Charter, documentation, model weights | **CC BY-SA 4.0** | [LICENSE-DOCS](../LICENSE-DOCS) |
| Training data | Each source's own licence | [DATA.md](../DATA.md) |
| Contributions | Developer Certificate of Origin (sign-off), no CLA | [CONTRIBUTING.md](../CONTRIBUTING.md) |

## Why AGPL-3.0 rather than Apache-2.0

| | Apache-2.0 | AGPL-3.0 |
|---|---|---|
| Anyone may use, study, change and share it | Yes | Yes |
| Anyone may sell it or charge for a service built on it | Yes | Yes (no open-source licence can forbid this) |
| A company may make a **closed** version and keep its changes secret | **Yes** | **No.** Anyone who distributes a modified version, **or runs it as an online service**, must publish its full source under the AGPL |
| Patent protection for users | Explicit patent grant | Explicit patent grant |
| Adoption by companies | Very wide | Lower; some companies avoid AGPL |

The brief says the project must stay **free for everyone, forever** and that no one should be able to profit from *access*. Apache-2.0 would let someone take the project, improve it in private, and sell access to a closed version that the public cannot inspect. AGPL-3.0 makes that impossible: any improved version that reaches people must be shared back. Lower corporate adoption is an acceptable price, arguably a feature, for this project.

**Honest limit:** no open-source licence can stop someone from *charging money*. Open-source definitions require allowing commercial use. What AGPL guarantees is that a free, open copy can always exist, and that improvements cannot be locked away. The project's own promise (P1) is that **it** never charges.

## Why not a "non-commercial" or "responsible AI" licence?

Licences like CC BY-NC or OpenRAIL add usage restrictions. They are **not open source**: they block legitimate uses (a hospital, a co-operative, a teacher paid by a school), are hard to enforce, and cannot be combined with most open data. Our safety protections live in the charter and the software instead, where they can be inspected and tested.

## Why CC BY-SA 4.0 for the charter, docs and weights

- It is share-alike, the same "keep it open" idea as AGPL, but designed for text and other non-code works.
- Wikipedia, a major training source, is CC BY-SA. Whether model weights legally inherit their training data's licence is **unsettled law**. Using CC BY-SA for the weights respects Wikipedia's terms either way.

## Why a sign-off (DCO) instead of a contributor licence agreement (CLA)

A CLA usually gives one organisation the right to re-license everyone's contributions, including as proprietary software. With a DCO sign-off, each contributor keeps their own copyright. Because the project then has many copyright holders, re-licensing it as closed software is practically impossible. That protects "free forever" from the project's own future maintainers too.

*Not legal advice. If the project grows, a review by a lawyer specialising in open source is worthwhile; this is noted in [ROADMAP.md](../ROADMAP.md).*
