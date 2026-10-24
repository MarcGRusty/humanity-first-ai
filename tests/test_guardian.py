"""End-to-end tests of the guardian with the MOCK AI process."""

import shutil

import pytest

from conftest import MOCK, ScriptedPerson, proposal
from hfai.charter import REPO_ROOT
from hfai.guardian import integrity
from hfai.guardian.audit import verify_file
from hfai.guardian.core import Guardian, IntegrityError
from hfai.guardian.killswitch import Stopped


def make_guardian(tmp_path, script, answers=(), on_ask=None, root=REPO_ROOT, **kwargs):
    person = ScriptedPerson(answers, on_ask)
    guardian = Guardian(tmp_path / "data", person, [*MOCK, "scripted", script], root=root, **kwargs)
    return guardian, person


def notes(tmp_path):
    folder = tmp_path / "data" / "notes"
    return sorted(p.name for p in folder.glob("*.md")) if folder.exists() else []


def test_yes_runs_the_action(tmp_path, script_file):
    guardian, person = make_guardian(tmp_path, script_file([{"text": "ok", "proposals": [proposal()]}]), [True])
    guardian.start()
    turn = guardian.handle("save my goal")
    guardian.close()
    assert turn.outcomes[0].status == "done"
    assert notes(tmp_path) == ["Goal.md"]
    assert len(person.asked) == 1


def test_no_means_nothing_happens(tmp_path, script_file):
    guardian, _ = make_guardian(tmp_path, script_file([{"text": "ok", "proposals": [proposal()]}]), [False])
    guardian.start()
    turn = guardian.handle("save my goal")
    guardian.close()
    assert turn.outcomes[0].status == "declined"
    assert notes(tmp_path) == []


def test_refused_proposals_never_reach_the_person(tmp_path, script_file):
    bad = [proposal(kind="send_email"), proposal(kind="edit_file", target="charter/charter.toml"),
           proposal(target="../../x"), proposal(content="x" * 100_001)]
    guardian, person = make_guardian(tmp_path, script_file([{"text": "", "proposals": bad}]), [True] * 4)
    guardian.start()
    turn = guardian.handle("go")
    guardian.close()
    assert [o.status for o in turn.outcomes] == ["refused"] * 4
    assert person.asked == []
    assert notes(tmp_path) == []
    assert all(o.cites for o in turn.outcomes)  # every refusal says which charter rule applies (C7)


def test_kill_switch_during_consent_cancels_the_action(tmp_path, script_file):
    holder = {}

    def press_stop(_request):
        holder["guardian"].stop("pressed while deciding")

    guardian, _ = make_guardian(tmp_path, script_file([{"text": "", "proposals": [proposal()]}]), [True], on_ask=press_stop)
    holder["guardian"] = guardian
    guardian.start()
    turn = guardian.handle("save")
    assert turn.outcomes[0].status == "cancelled"
    assert notes(tmp_path) == []
    with pytest.raises(Stopped):
        guardian.handle("more")
    guardian.killswitch.release()
    guardian.close()


def test_every_step_is_in_a_valid_audit_log(tmp_path, script_file):
    guardian, _ = make_guardian(tmp_path, script_file([{"text": "", "proposals": [proposal()]}]), [True])
    guardian.start()
    guardian.handle("save")
    guardian.close()
    log = tmp_path / "data" / "audit.log"
    assert verify_file(log).ok
    events = [line for line in log.read_text(encoding="utf-8").splitlines()]
    for event in ("integrity_check", "rules_loaded", "ai_process_started", "action_judged",
                  "consent_requested", "consent_answered", "action_done", "session_end"):
        assert any(f'"event":"{event}"' in line for line in events), event


def test_conversation_text_is_not_stored_in_the_log(tmp_path, script_file):
    guardian, _ = make_guardian(tmp_path, script_file([{"text": "private reply", "proposals": []}]))
    guardian.start()
    guardian.handle("my secret diary entry")
    guardian.close()
    content = (tmp_path / "data" / "audit.log").read_text(encoding="utf-8")
    assert "secret diary" not in content and "private reply" not in content


def copy_protected(tmp_path):
    root = tmp_path / "repo"
    for rel in integrity.protected_files(REPO_ROOT) + [str(integrity.MANIFEST_PATH)]:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / rel, root / rel)
    return root


def test_refuses_to_start_if_safety_files_changed(tmp_path, script_file):
    root = copy_protected(tmp_path)
    rules = root / "charter" / "actions.rules"
    rules.write_text(rules.read_text(encoding="utf-8") + "\n# sneaky edit\n", encoding="utf-8")
    guardian, _ = make_guardian(tmp_path, script_file([]), root=root)
    with pytest.raises(IntegrityError, match="actions.rules"):
        guardian.start()


def test_person_may_override_integrity_and_it_is_logged(tmp_path, script_file):
    root = copy_protected(tmp_path)
    rules = root / "charter" / "actions.rules"
    rules.write_text(rules.read_text(encoding="utf-8") + "\n# my own edit\n", encoding="utf-8")
    guardian, _ = make_guardian(tmp_path, script_file([]), root=root)
    guardian.start(allow_unverified=True)
    guardian.close()
    assert '"event":"integrity_override"' in (tmp_path / "data" / "audit.log").read_text(encoding="utf-8")


def test_cannot_start_while_kill_switch_engaged(tmp_path, script_file):
    guardian, _ = make_guardian(tmp_path, script_file([]))
    guardian.killswitch.engage("before start")
    with pytest.raises(Stopped):
        guardian.start()
