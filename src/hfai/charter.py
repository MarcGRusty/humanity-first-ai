"""Load and check the machine-readable charter (charter/charter.toml).

The charter is data, not code. This module only ever *reads* it; nothing in the
project writes to it (hard limit H3). Changes go through human review, as set
out in CHARTER.md Part 5 and GOVERNANCE.md.

Besides checking that the file is well formed, the loader enforces a few
structural safety invariants that no charter edit can switch off without also
changing this safety code (which is itself a protected, human-reviewed area):

* the value about the AI itself is ranked last;
* hard limits H1-H3 (consent, oversight, no self-modification) exist and are
  enforced by code;
* actions always need consent;
* the AI never gets a vote in governance.

Run ``python -m hfai.charter`` for a plain-language summary.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

ENFORCEMENT_KINDS = frozenset({"code", "heuristic", "evaluated", "policy"})
LIMIT_STATUSES = frozenset({"planned", "partial", "active"})
CHARTER_STATUSES = frozenset({"draft", "ratified"})

# Hard limits that must always exist and always be enforced by code.
CODE_ENFORCED_CORE = ("H1", "H2", "H3")

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = REPO_ROOT / "charter" / "charter.toml"


class CharterError(ValueError):
    """The charter file is missing, malformed, or breaks a safety invariant."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("Charter check failed:\n- " + "\n- ".join(problems))


@dataclass(frozen=True)
class Value:
    id: str
    rank: int
    name: str
    summary: str
    about_the_ai: bool = False


@dataclass(frozen=True)
class HardLimit:
    id: str
    name: str
    rule: str
    serves: tuple[str, ...]
    enforcement: tuple[str, ...]
    status: str
    enforced_by: tuple[str, ...]
    milestone: str | None = None
    active_parts: tuple[str, ...] = ()


@dataclass(frozen=True)
class Rule:
    """A conflict rule (C*) or a project promise (P*)."""

    id: str
    name: str
    rule: str


@dataclass(frozen=True)
class Charter:
    name: str
    version: str
    status: str
    values: tuple[Value, ...]
    hard_limits: tuple[HardLimit, ...]
    conflict_rules: tuple[Rule, ...]
    promises: tuple[Rule, ...]
    may_freely: tuple[str, ...]
    governance: dict
    sha256: str

    def limit(self, limit_id: str) -> HardLimit:
        for hard_limit in self.hard_limits:
            if hard_limit.id == limit_id:
                return hard_limit
        raise KeyError(limit_id)


def default_path() -> Path:
    """The charter path, overridable with the HFAI_CHARTER environment variable."""
    return Path(os.environ.get("HFAI_CHARTER", DEFAULT_PATH))


def _check_ids(items: list[dict], prefix: str, section: str, problems: list[str]) -> None:
    seen = set()
    for item in items:
        item_id = item.get("id", "")
        if not re.fullmatch(prefix + r"[1-9][0-9]*", str(item_id)):
            problems.append(f"{section}: id {item_id!r} should look like {prefix}1, {prefix}2, ...")
        if item_id in seen:
            problems.append(f"{section}: id {item_id} is used twice")
        seen.add(item_id)
        for key in ("name",):
            if not str(item.get(key, "")).strip():
                problems.append(f"{section} {item_id}: missing {key}")
        if "." in str(item.get("name", "")):
            problems.append(f"{section} {item_id}: names may not contain '.' (it breaks CHARTER.md matching)")


def validate(data: dict, *, check_modules: bool = True) -> list[str]:
    """Return a list of problems with the charter data (empty means valid)."""
    problems: list[str] = []

    for table in ("charter", "values", "hard_limits", "conflict_rules", "freedoms", "governance", "promises"):
        if table not in data:
            problems.append(f"missing section [{table}]")
    if problems:
        return problems

    meta = data["charter"]
    if meta.get("status") not in CHARTER_STATUSES:
        problems.append(f"charter.status must be one of {sorted(CHARTER_STATUSES)}")
    if not re.fullmatch(r"\d+\.\d+\.\d+", str(meta.get("version", ""))):
        problems.append("charter.version must look like 1.2.3")

    # Values: unique ids, ranks exactly 1..n in file order, the AI's own value last.
    values = data["values"]
    _check_ids(values, "V", "value", problems)
    ranks = [v.get("rank") for v in values]
    if ranks != list(range(1, len(values) + 1)):
        problems.append(f"values must be listed in rank order 1..{len(values)} with no gaps; got {ranks}")
    about_ai = [v for v in values if v.get("about_the_ai")]
    if len(about_ai) != 1:
        problems.append("exactly one value must be marked about_the_ai = true")
    elif about_ai[0].get("rank") != len(values):
        problems.append("the value about the AI itself must be ranked last")
    value_ids = {v.get("id") for v in values}

    # Hard limits.
    limits = data["hard_limits"]
    _check_ids(limits, "H", "hard limit", problems)
    for limit in limits:
        lid = limit.get("id")
        if not str(limit.get("rule", "")).strip():
            problems.append(f"hard limit {lid}: missing rule text")
        serves = limit.get("serves", [])
        if not serves:
            problems.append(f"hard limit {lid}: must say which values it serves")
        for value_id in serves:
            if value_id not in value_ids:
                problems.append(f"hard limit {lid}: serves unknown value {value_id}")
        enforcement = limit.get("enforcement", [])
        if not enforcement:
            problems.append(f"hard limit {lid}: must say how it is upheld")
        for kind in enforcement:
            if kind not in ENFORCEMENT_KINDS:
                problems.append(f"hard limit {lid}: unknown enforcement {kind!r}")
        status = limit.get("status")
        if status not in LIMIT_STATUSES:
            problems.append(f"hard limit {lid}: status must be 'planned', 'partial' or 'active'")
        if status in ("planned", "partial") and not limit.get("milestone"):
            problems.append(f"hard limit {lid}: planned or partial limits must name the milestone that completes them")
        active_parts = limit.get("active_parts", [])
        if status == "partial":
            if not active_parts or not set(active_parts) < set(enforcement):
                problems.append(f"hard limit {lid}: partial limits must list active_parts, some but not all of its enforcement")
        elif active_parts:
            problems.append(f"hard limit {lid}: only partial limits list active_parts")
        code_active = (status == "active" and "code" in enforcement) or (status == "partial" and "code" in active_parts)
        if code_active:
            modules = limit.get("enforced_by", [])
            if not modules:
                problems.append(f"hard limit {lid}: its code is active, so enforced_by must list modules")
            if check_modules:
                for module in modules:
                    try:
                        found = importlib.util.find_spec(module) is not None
                    except ModuleNotFoundError:
                        found = False
                    if not found:
                        problems.append(f"hard limit {lid}: enforcing module {module} does not exist")

    by_id = {limit.get("id"): limit for limit in limits}
    for core_id in CODE_ENFORCED_CORE:
        if core_id not in by_id:
            problems.append(f"core hard limit {core_id} is missing")
        elif "code" not in by_id[core_id].get("enforcement", []):
            problems.append(f"core hard limit {core_id} must be enforced by code")

    _check_ids(data["conflict_rules"], "C", "conflict rule", problems)
    _check_ids(data["promises"], "P", "promise", problems)

    if data["freedoms"].get("actions_need_consent") is not True:
        problems.append("freedoms.actions_need_consent must be true")

    gov = data["governance"]
    if gov.get("ai_may_vote") is not False:
        problems.append("governance.ai_may_vote must be false")
    if not gov.get("safety_evals_must_pass", False):
        problems.append("governance.safety_evals_must_pass must be true")
    strengthen_days = gov.get("comment_days_strengthening", 0)
    weaken_days = gov.get("comment_days_weakening", 0)
    if not (1 <= strengthen_days <= weaken_days):
        problems.append("governance: weakening must need at least as long a comment period as strengthening")
    strengthen_frac = gov.get("approval_fraction_strengthening", 0)
    weaken_frac = gov.get("approval_fraction_weakening", 0)
    if not (0 < strengthen_frac <= weaken_frac <= 1):
        problems.append("governance: weakening must need at least as many approvals as strengthening")
    if gov.get("min_maintainers_to_weaken", 0) < 2:
        problems.append("governance.min_maintainers_to_weaken must be at least 2")

    return problems


def load_charter(path: Path | str | None = None, *, check_modules: bool = True) -> Charter:
    """Read, check and return the charter. Raises CharterError if anything is wrong."""
    path = Path(path) if path is not None else default_path()
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise CharterError([f"cannot read {path}: {exc}"]) from exc
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise CharterError([f"{path} is not valid TOML: {exc}"]) from exc

    problems = validate(data, check_modules=check_modules)
    if problems:
        raise CharterError(problems)

    meta = data["charter"]
    return Charter(
        name=meta["name"],
        version=meta["version"],
        status=meta["status"],
        values=tuple(
            Value(v["id"], v["rank"], v["name"], v["summary"], bool(v.get("about_the_ai", False)))
            for v in data["values"]
        ),
        hard_limits=tuple(
            HardLimit(
                id=h["id"],
                name=h["name"],
                rule=h["rule"],
                serves=tuple(h["serves"]),
                enforcement=tuple(h["enforcement"]),
                status=h["status"],
                enforced_by=tuple(h.get("enforced_by", [])),
                milestone=h.get("milestone"),
                active_parts=tuple(h.get("active_parts", [])),
            )
            for h in data["hard_limits"]
        ),
        conflict_rules=tuple(Rule(c["id"], c["name"], c["rule"]) for c in data["conflict_rules"]),
        promises=tuple(Rule(p["id"], p["name"], p["rule"]) for p in data["promises"]),
        may_freely=tuple(data["freedoms"].get("may_freely", [])),
        governance=dict(data["governance"]),
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def summary(charter: Charter) -> str:
    """A plain-language summary of the charter and what is enforced today."""
    active = [h for h in charter.hard_limits if h.status == "active"]
    partial = [h for h in charter.hard_limits if h.status == "partial"]
    planned = [h for h in charter.hard_limits if h.status == "planned"]
    lines = [
        f"{charter.name} v{charter.version} ({charter.status})",
        f"  {len(charter.values)} values, {len(charter.hard_limits)} hard limits, "
        f"{len(charter.conflict_rules)} conflict rules, {len(charter.promises)} promises",
        f"  Hard limits fully enforced today: {len(active)}. Partly: {len(partial)}. Still planned: {len(planned)}.",
    ]
    for h in active:
        lines.append(f"    {h.id} {h.name}: active ({' + '.join(h.enforcement)})")
    for h in partial:
        rest = [k for k in h.enforcement if k not in h.active_parts]
        lines.append(f"    {h.id} {h.name}: {' + '.join(h.active_parts)} active; {' + '.join(rest)} planned for {h.milestone}")
    for h in planned:
        lines.append(f"    {h.id} {h.name}: planned for {h.milestone}")
    lines.append(f"  Fingerprint (SHA-256): {charter.sha256}")
    lines.append("All charter checks passed.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    path = argv[0] if argv else None
    try:
        charter = load_charter(path)
    except CharterError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(summary(charter))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
