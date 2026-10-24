import json

import pytest

from hfai.guardian.consent import ConsentAnswer

MOCK = ["-m", "hfai.worker.mock"]


class ScriptedPerson:
    """Test stand-in for a person answering consent questions."""

    def __init__(self, answers=(), on_ask=None):
        self.answers = list(answers)
        self.asked = []
        self.on_ask = on_ask

    def ask(self, request):
        self.asked.append(request)
        if self.on_ask:
            self.on_ask(request)
        return ConsentAnswer(self.answers.pop(0) if self.answers else False, "test")


@pytest.fixture
def script_file(tmp_path):
    def make(entries):
        path = tmp_path / "script.json"
        path.write_text(json.dumps(entries), encoding="utf-8")
        return str(path)

    return make


def proposal(kind="save_note", target="Goal", content="Run 5 km", reason="asked"):
    return {"kind": kind, "target": target, "content": content, "reason": reason}
