"""Tests for the charter: it must load, pass its safety invariants, and say
exactly the same thing in CHARTER.md (for people) and charter.toml (for code)."""

import copy
import re
import tomllib

import pytest

from hfai.charter import REPO_ROOT, CharterError, load_charter, validate

TOML_PATH = REPO_ROOT / "charter" / "charter.toml"
MD_PATH = REPO_ROOT / "CHARTER.md"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


@pytest.fixture(scope="module")
def data():
    return tomllib.loads(TOML_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def md():
    return _norm(MD_PATH.read_text(encoding="utf-8"))


def test_real_charter_is_valid():
    charter = load_charter(TOML_PATH)
    assert len(charter.sha256) == 64
    assert charter.values[-1].about_the_ai


# --- CHARTER.md and charter.toml must match word for word -----------------


def test_header_states_version_and_status(data, md):
    meta = data["charter"]
    assert f"Version {meta['version']}. Status: {meta['status'].upper()}" in md


def test_values_match_and_are_in_order(data, md):
    positions = []
    for value in data["values"]:
        text = _norm(f"**{value['id']}. {value['name']}.** {value['summary']}")
        assert text in md, f"CHARTER.md is missing or differs for {value['id']}"
        positions.append(md.index(text))
    assert positions == sorted(positions), "values appear in a different order in CHARTER.md"


def _upheld_line(limit) -> str:
    how = " + ".join(limit["enforcement"])
    if limit["status"] == "planned":
        status = f"planned, built in {limit['milestone']}"
    else:
        status = "active"
    return f"How it is upheld: {how}. Status: {status}."


def test_hard_limits_match_including_enforcement_status(data, md):
    for limit in data["hard_limits"]:
        text = _norm(f"**{limit['id']}. {limit['name']}.** {limit['rule']} {_upheld_line(limit)}")
        assert text in md, f"CHARTER.md is missing or differs for {limit['id']}"


@pytest.mark.parametrize("section", ["conflict_rules", "promises"])
def test_rules_and_promises_match(data, md, section):
    for item in data[section]:
        text = _norm(f"**{item['id']}. {item['name']}.** {item['rule']}")
        assert text in md, f"CHARTER.md is missing or differs for {item['id']}"


def test_markdown_has_no_extra_ids(data, md):
    known = {item["id"] for section in ("values", "hard_limits", "conflict_rules", "promises") for item in data[section]}
    in_md = set(re.findall(r"\*\*([VHCP][0-9]+)\.", md))
    assert in_md == known


def test_freedoms_listed(data, md):
    for item in data["freedoms"]["may_freely"]:
        assert f"- {item}" in md


def test_governance_numbers_match(data, md):
    gov = data["governance"]
    assert f"at least **{gov['comment_days_strengthening']} days**" in md
    assert f"at least **{gov['comment_days_weakening']} days**" in md
    assert f"fewer than **{gov['min_maintainers_to_weaken']}** maintainers" in md


# --- The loader must refuse charters that break safety invariants ----------


def _problems_after(data, mutate):
    broken = copy.deepcopy(data)
    mutate(broken)
    return validate(broken, check_modules=False)


def test_valid_baseline(data):
    assert validate(data, check_modules=False) == []


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda d: d["values"].reverse(), "rank order"),
        (lambda d: d["values"][-1].update(about_the_ai=False) or d["values"][0].update(about_the_ai=True), "ranked last"),
        (lambda d: d["hard_limits"][0].update(serves=["V99"]), "unknown value"),
        (lambda d: d["hard_limits"][0].update(enforcement=["vibes"]), "unknown enforcement"),
        (lambda d: d["hard_limits"][0].update(enforcement=["policy"]), "H1 must be enforced by code"),
        (lambda d: d["hard_limits"].pop(1), "H2 is missing"),
        (lambda d: d["hard_limits"][3].update(status="planned", milestone=""), "must name the milestone"),
        (lambda d: d["hard_limits"][0].update(status="active", enforced_by=[]), "enforced_by must list modules"),
        (lambda d: d["freedoms"].update(actions_need_consent=False), "actions_need_consent"),
        (lambda d: d["governance"].update(ai_may_vote=True), "ai_may_vote"),
        (lambda d: d["governance"].update(comment_days_weakening=1), "comment period"),
        (lambda d: d["governance"].update(approval_fraction_weakening=0.5), "approvals"),
        (lambda d: d["governance"].update(min_maintainers_to_weaken=1), "min_maintainers_to_weaken"),
        (lambda d: d["conflict_rules"][1].update(id="C1"), "used twice"),
        (lambda d: d.pop("governance"), "missing section"),
    ],
)
def test_invariant_violations_are_rejected(data, mutate, expected):
    problems = _problems_after(data, mutate)
    assert any(expected in p for p in problems), problems


def test_active_limit_with_missing_module_is_rejected(data):
    broken = copy.deepcopy(data)
    broken["hard_limits"][0].update(status="active", enforced_by=["hfai.does_not_exist"])
    problems = validate(broken, check_modules=True)
    assert any("does not exist" in p for p in problems)


def test_bad_file_raises(tmp_path):
    bad = tmp_path / "charter.toml"
    bad.write_text("this is not = = toml", encoding="utf-8")
    with pytest.raises(CharterError):
        load_charter(bad)
