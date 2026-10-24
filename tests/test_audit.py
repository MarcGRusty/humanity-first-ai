"""The audit log must record entries in a chain that shows any tampering."""

import json

import pytest

from hfai.guardian.audit import AuditLog, verify_file


def make_log(tmp_path, n=5):
    log = AuditLog(tmp_path / "audit.log")
    for i in range(n):
        log.append("event", number=i)
    return log


def rewrite(path, transform):
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(transform(lines)) + "\n", encoding="utf-8")


def test_fresh_log_verifies(tmp_path):
    log = make_log(tmp_path)
    result = log.verify()
    assert result.ok and result.entries == 5
    assert result.head == log.head()


def test_edited_entry_detected(tmp_path):
    log = make_log(tmp_path)

    def edit(lines):
        entry = json.loads(lines[2])
        entry["details"]["number"] = 99
        lines[2] = json.dumps(entry)
        return lines

    rewrite(log.path, edit)
    result = verify_file(log.path)
    assert not result.ok and result.bad_line == 3
    assert "changed after it was written" in result.problem


@pytest.mark.parametrize(
    "transform",
    [
        lambda lines: lines[:1] + lines[2:],  # deleted entry
        lambda lines: [lines[1], lines[0]] + lines[2:],  # reordered
        lambda lines: lines[:2] + [lines[1]] + lines[2:],  # duplicated
    ],
)
def test_removed_reordered_inserted_detected(tmp_path, transform):
    log = make_log(tmp_path)
    rewrite(log.path, transform)
    assert not verify_file(log.path).ok


def test_truncation_needs_a_saved_fingerprint(tmp_path):
    log = make_log(tmp_path)
    saved_head = log.head()
    rewrite(log.path, lambda lines: lines[:-1])
    assert verify_file(log.path).ok  # honest limit: cutting the end is invisible on its own...
    assert not verify_file(log.path, expected_head=saved_head).ok  # ...but caught with a saved fingerprint


def test_refuses_to_append_to_damaged_log(tmp_path):
    log = make_log(tmp_path)
    rewrite(log.path, lambda lines: lines[:1] + ["not json"] + lines[1:])
    with pytest.raises(RuntimeError, match="TAMPERED OR DAMAGED"):
        AuditLog(log.path)


def test_two_writers_keep_one_valid_chain(tmp_path):
    # Simulates the guardian and the 'stop' command writing to the same log.
    first = AuditLog(tmp_path / "audit.log")
    second = AuditLog(tmp_path / "audit.log")
    for i in range(10):
        (first if i % 2 else second).append("event", number=i)
    result = verify_file(tmp_path / "audit.log")
    assert result.ok and result.entries == 10


def test_long_details_are_clipped(tmp_path):
    log = AuditLog(tmp_path / "audit.log")
    entry = log.append("event", text="x" * 5000)
    assert len(entry["details"]["text"]) < 1100
