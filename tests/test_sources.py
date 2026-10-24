"""Checks data/sources.toml against the data rules in DATA.md."""

import tomllib

import pytest

from hfai.charter import REPO_ROOT

SOURCES = tomllib.loads((REPO_ROOT / "data" / "sources.toml").read_text(encoding="utf-8"))
DATA_MD = (REPO_ROOT / "DATA.md").read_text(encoding="utf-8")
POLICY = SOURCES["policy"]
ALL = SOURCES["sources"]
USED = [s for s in ALL if s["status"] != "excluded"]
EXCLUDED = [s for s in ALL if s["status"] == "excluded"]

REQUIRED = ("id", "name", "url", "licence", "uses", "languages", "human_written", "ai_text_risk", "status", "verified")


@pytest.mark.parametrize("source", ALL, ids=lambda s: s["id"])
def test_required_fields(source):
    for field in REQUIRED:
        assert field in source, f"{source.get('id')} is missing {field}"
    assert source["status"] in {"candidate", "in_use", "excluded"}
    assert source["ai_text_risk"] in {"none", "low", "some"}


def test_ids_unique():
    ids = [s["id"] for s in ALL]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("source", USED, ids=lambda s: s["id"])
def test_used_sources_are_open_and_human_written(source):
    assert source["licence"] in POLICY["allowed_licences"]
    assert source["human_written"] is True
    assert source["uses"], "a source we keep must say what it is used for"


@pytest.mark.parametrize("source", USED, ids=lambda s: s["id"])
def test_never_allowed_datasets_are_not_used(source):
    haystack = (source["id"] + " " + source["name"] + " " + source.get("hf_dataset", "")).lower()
    for banned in POLICY["never_allowed"]:
        assert banned not in haystack, f"{source['id']} matches never-allowed dataset {banned!r}"


@pytest.mark.parametrize("source", EXCLUDED, ids=lambda s: s["id"])
def test_excluded_sources_give_a_reason(source):
    assert source.get("reason", "").strip()


def test_in_use_sources_are_verified():
    for source in ALL:
        if source["status"] == "in_use":
            assert source["verified"], f"{source['id']} is in use but its licence has not been verified"


@pytest.mark.parametrize("source", ALL, ids=lambda s: s["id"])
def test_every_source_documented_in_data_md(source):
    assert f"`{source['id']}`" in DATA_MD
