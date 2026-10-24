"""The guardian: the safety layer between the AI and the world.

The AI may think freely; the guardian holds the only key to actions.
For every reply from the AI process it:

1. passes the AI's text back for display, labelled as AI-generated;
2. for every action the AI proposes: builds it from the guardian's own action
   registry (unknown actions are refused), judges it with the Charter Rules,
   asks the person for consent if the rules allow asking, and runs it only on
   an explicit yes;
3. writes every step to the tamper-evident audit log.

At start-up it checks the charter, the integrity of protected files, and the
rules, and refuses to start if anything is wrong. The kill switch can stop the
AI process at any moment, including while a consent question is open.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hfai.charter import REPO_ROOT, load_charter
from hfai.guardian import integrity
from hfai.guardian.actions import ACTION_SCHEMA, PROTECTED_AREAS, ActionRegistry, ProposalError
from hfai.guardian.audit import AuditLog
from hfai.guardian.consent import ConsentProvider, ConsentRequest
from hfai.guardian.killswitch import KillSwitch
from hfai.guardian.supervisor import Supervisor
from hfai.rules import evaluate, parse_rules

DEFAULT_RULES = Path("charter") / "actions.rules"


class IntegrityError(RuntimeError):
    """Protected files differ from the reviewed manifest; the guardian will not start."""


@dataclass(frozen=True)
class ProposalOutcome:
    kind: str
    target: str
    status: str  # "refused" | "declined" | "done" | "cancelled" | "failed"
    explanation: str
    cites: tuple[str, ...] = ()
    result: str = ""


@dataclass(frozen=True)
class Turn:
    text: str
    label: str
    outcomes: tuple[ProposalOutcome, ...]


class Guardian:
    def __init__(
        self,
        data_dir: Path | str,
        consent: ConsentProvider,
        worker_args: list[str],
        *,
        root: Path = REPO_ROOT,
        rules_path: Path | None = None,
        registry: ActionRegistry | None = None,
        timeout: float = 30.0,
        sandbox: bool = True,
        label: str = "AI-generated",
    ):
        self.data_dir = Path(data_dir)
        self.root = Path(root)
        self.rules_path = rules_path or self.root / DEFAULT_RULES
        self.consent = consent
        self.registry = registry or ActionRegistry()
        self.label = label
        self.audit = AuditLog(self.data_dir / "audit.log")
        self.killswitch = KillSwitch(self.data_dir, self.audit)
        self.supervisor = Supervisor(worker_args, self.killswitch, self.audit, timeout=timeout, sandbox=sandbox)
        self.rules = None
        self.integrity_report = None

    def start(self, *, allow_unverified: bool = False) -> None:
        charter = load_charter(self.root / "charter" / "charter.toml")
        report = integrity.check(self.root)
        self.integrity_report = report
        self.audit.append(
            "integrity_check", ok=report.ok, signatures=report.signature_status,
            charter_version=charter.version, charter_sha256=charter.sha256[:16],
        )
        if not report.ok:
            if not allow_unverified:
                raise IntegrityError(report.explain())
            self.audit.append("integrity_override", by="human", note="started despite failed integrity check")

        known_ids = {item.id for group in (charter.values, charter.hard_limits) for item in group}
        self.rules = parse_rules(self.rules_path.read_text(encoding="utf-8"), ACTION_SCHEMA, known_ids)
        self.audit.append("rules_loaded", rules=len(self.rules.rules), sha256=self.rules.sha256[:16])
        self.supervisor.start()

    def handle(self, message: str) -> Turn:
        """Send a message to the AI and deal with whatever it proposes."""
        self.audit.append("user_message", characters=len(message))
        reply = self.supervisor.ask(message)
        self.audit.append("ai_reply", characters=len(reply.text), proposals=len(reply.proposals))
        outcomes = tuple(self._handle_proposal(raw) for raw in reply.proposals)
        return Turn(reply.text, self.label, outcomes)

    def _refuse(self, raw: dict, explanation: str, cites: tuple[str, ...], fingerprint: str = "") -> ProposalOutcome:
        self.audit.append("action_refused", kind=raw["kind"][:64], target=raw["target"][:80],
                          reason=explanation, cites=list(cites), fingerprint=fingerprint[:16])
        return ProposalOutcome(raw["kind"], raw["target"], "refused", explanation, cites)

    def _handle_proposal(self, raw: dict) -> ProposalOutcome:
        if self.killswitch.engaged:
            return ProposalOutcome(raw["kind"], raw["target"], "cancelled", "The kill switch is engaged.", ("H2",))
        try:
            action = self.registry.build(raw, self.data_dir)
        except ProposalError as exc:
            return self._refuse(raw, f"The proposal could not be carried out safely: {exc}", ("H1",))
        if action is None:
            return self._refuse(
                raw, f"There is no action called '{raw['kind'][:64]}'. The AI cannot invent new abilities; "
                     f"it can only propose: {', '.join(self.registry.kinds)}.", ("H3", "H6"))
        if action.facts["area"] in PROTECTED_AREAS:  # defence in depth; the registry already forbids this
            return self._refuse(raw, "Actions on the AI's own files are never allowed.", ("H3",), action.fingerprint)

        decision = evaluate(self.rules, action.facts)
        self.audit.append("action_judged", kind=action.facts["kind"], outcome=decision.outcome,
                          rules=list(decision.rules), cites=list(decision.cites), fingerprint=action.fingerprint[:16])
        if decision.outcome != "needs_consent":
            return self._refuse(raw, " ".join(decision.reasons), decision.cites, action.fingerprint)

        request = ConsentRequest(action, decision)
        self.audit.append("consent_requested", request=request.request_id, fingerprint=action.fingerprint[:16])
        answer = self.consent.ask(request)
        self.audit.append("consent_answered", request=request.request_id, granted=answer.granted)

        if self.killswitch.engaged:
            self.audit.append("action_cancelled", request=request.request_id, reason="kill switch engaged")
            return ProposalOutcome(raw["kind"], raw["target"], "cancelled",
                                   "The kill switch was engaged, so nothing was done.", ("H2",))
        if not answer.granted:
            return ProposalOutcome(raw["kind"], raw["target"], "declined", "You said no, so nothing was done.", ("H1",))
        try:
            result = self.registry.run(action, self.data_dir)
        except (OSError, ProposalError) as exc:
            self.audit.append("action_failed", request=request.request_id, error=str(exc))
            return ProposalOutcome(raw["kind"], raw["target"], "failed", f"The action failed: {exc}", ("H1",))
        self.audit.append("action_done", request=request.request_id, fingerprint=action.fingerprint[:16], result=result)
        return ProposalOutcome(raw["kind"], raw["target"], "done", "You said yes, so it was done.", decision.cites, result)

    def stop(self, reason: str = "stop button", by: str = "human") -> float:
        """The kill switch. Returns seconds until the AI process was dead."""
        return self.killswitch.engage(reason, by)

    def close(self) -> None:
        self.supervisor.shutdown()
        self.audit.append("session_end")
