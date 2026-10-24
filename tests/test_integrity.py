"""Integrity checks on the charter, rules and safety code, including signatures."""

import base64
import json
import shutil

import pytest

from hfai.charter import REPO_ROOT
from hfai.guardian import integrity


def test_repository_matches_its_manifest():
    report = integrity.check(REPO_ROOT)
    assert report.ok, report.explain() + "  (after a reviewed change, run: python -m hfai.guardian integrity --update)"


def test_protected_files_include_the_safety_layer():
    files = integrity.protected_files(REPO_ROOT)
    for expected in ("CHARTER.md", "charter/charter.toml", "charter/actions.rules", "src/hfai/charter.py",
                     "src/hfai/guardian/core.py", "src/hfai/rules/language.py", "src/hfai/worker/protocol.py"):
        assert expected in files


@pytest.fixture
def root(tmp_path):
    copy = tmp_path / "repo"
    for rel in integrity.protected_files(REPO_ROOT) + [str(integrity.MANIFEST_PATH)]:
        (copy / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / rel, copy / rel)
    return copy


def test_change_missing_and_extra_files_detected(root):
    (root / "CHARTER.md").write_text("changed", encoding="utf-8")
    (root / "src/hfai/rules/__init__.py").unlink()
    (root / "src/hfai/guardian/backdoor.py").write_text("x = 1", encoding="utf-8")
    report = integrity.check(root)
    assert not report.ok
    assert report.changed == ("CHARTER.md",)
    assert report.missing == ("src/hfai/rules/__init__.py",)
    assert report.unexpected == ("src/hfai/guardian/backdoor.py",)


def trust(root, publics, threshold=1):
    keys = [{"key_id": integrity.key_id(p), "public_key": base64.b64encode(p).decode(), "owner": f"m{i}"}
            for i, p in enumerate(publics)]
    (root / integrity.TRUSTED_KEYS_PATH).write_text(json.dumps({"threshold": threshold, "keys": keys}), encoding="utf-8")


def sign(root, private):
    path = root / integrity.MANIFEST_PATH
    manifest = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps(integrity.sign_manifest(manifest, private)), encoding="utf-8")


def test_valid_signature_passes(root):
    private, public = integrity.generate_keypair()
    trust(root, [public])
    sign(root, private)
    report = integrity.check(root)
    assert report.ok and report.signature_status.startswith("1 of 1")


def test_missing_signature_fails_once_keys_are_trusted(root):
    _, public = integrity.generate_keypair()
    trust(root, [public])
    assert not integrity.check(root).ok


def test_signature_from_untrusted_key_does_not_count(root):
    _, trusted_public = integrity.generate_keypair()
    stranger_private, _ = integrity.generate_keypair()
    trust(root, [trusted_public])
    sign(root, stranger_private)
    assert not integrity.check(root).ok


def test_editing_a_signed_manifest_breaks_the_signature(root):
    private, public = integrity.generate_keypair()
    trust(root, [public])
    sign(root, private)
    path = root / integrity.MANIFEST_PATH
    manifest = json.loads(path.read_text(encoding="utf-8"))
    (root / "CHARTER.md").write_text("changed", encoding="utf-8")
    manifest["files"]["CHARTER.md"] = integrity.compute_hashes(root)["CHARTER.md"]  # attacker updates the hash too
    path.write_text(json.dumps(manifest), encoding="utf-8")
    report = integrity.check(root)
    assert not report.ok
    assert any("INVALID" in note for note in report.notes)


def test_threshold_of_two(root):
    (p1, k1), (p2, k2) = integrity.generate_keypair(), integrity.generate_keypair()
    trust(root, [k1, k2], threshold=2)
    sign(root, p1)
    assert not integrity.check(root).ok
    sign(root, p2)
    assert integrity.check(root).ok
