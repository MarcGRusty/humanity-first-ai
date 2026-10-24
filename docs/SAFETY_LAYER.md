# The safety layer (the "guardian")

**Status: built and tested in milestone M1.** The AI behind it is still a MOCK stand-in until the real model arrives in M3; everything described here is real, working code.

The core idea: **the AI may think freely, but the guardian holds the only key to actions.** The guardian is separate from the AI, and the AI cannot change it.

```
   you  ◄──────────────►  GUARDIAN  ◄── messages only ──►  AI process
           consent            │                           (separate, sandboxed;
           questions,         │                            can only propose)
           kill switch        ├─ Charter Rules (what may be proposed)
                              ├─ action registry (the only actions that exist)
                              ├─ audit log (every decision)
                              └─ integrity check (charter + safety code unchanged)
```

## What each part does

| Part | What it guarantees | Charter |
|---|---|---|
| **Separate AI process** ([`supervisor.py`](../src/hfai/guardian/supervisor.py)) | The AI runs as its own operating-system process. It can only send messages, and every message is checked strictly; anything unexpected is discarded. | H1, H3 |
| **Action registry** ([`actions.py`](../src/hfai/guardian/actions.py)) | Only two actions exist in Phase 1, *save a note* and *export your notes*, both local and undoable. The AI cannot invent new ones. The facts about an action (where it acts, whether data leaves the device) are worked out by the guardian, never taken from the AI. | H3, H6, H9 |
| **Charter Rules** ([`rules/`](../src/hfai/rules/)) | Decide what the AI may *propose*. The language cannot express "act without consent". See [CHARTER_RULES.md](CHARTER_RULES.md). | H1 |
| **Consent gate** ([`consent.py`](../src/hfai/guardian/consent.py)) | Shows you exactly what will happen, the AI's stated reason (labelled as the AI's words), and asks yes or no. Default no. No "always allow". The action that runs is exactly the one you saw, matched by its fingerprint. | H1 |
| **Kill switch** ([`killswitch.py`](../src/hfai/guardian/killswitch.py)) | Kills the AI process instantly (it cannot catch or delay this) and keeps it stopped until a person releases it. Cancels any action waiting for consent. | H2 |
| **OS sandbox** ([`sandbox.py`](../src/hfai/guardian/sandbox.py)) | On Linux, the kernel itself forbids the AI process from writing, deleting or truncating any file, opening TCP connections, or signalling the guardian. | H3, H9 |
| **Audit log** ([`audit.py`](../src/hfai/guardian/audit.py)) | Every decision and action, in a hash chain that exposes edits, deletions and reordering. Stores decisions, not your conversations. | H3, H4 |
| **Integrity check** ([`integrity.py`](../src/hfai/guardian/integrity.py)) | At start-up, fingerprints the charter, rules and safety code and compares them with the reviewed manifest. Refuses to start if anything differs. Supports maintainers' digital signatures. | H3 |

## Using the controls

```bash
python -m hfai.guardian demo        # watch every safeguard work (MOCK AI, SIMULATED answers)
python -m hfai.guardian stop        # KILL SWITCH: works even if the app is frozen
python -m hfai.guardian release     # allow the AI to start again (people only)
python -m hfai.guardian status      # kill switch state and log check
python -m hfai.guardian log         # read the audit log
python -m hfai.guardian verify-log  # check the log for tampering
python -m hfai.guardian integrity   # check the charter and safety code are as reviewed
python -m hfai.guardian rules       # what the AI may propose, in plain language
```

Other ways to pull the kill switch: create a file named `STOP` in the data folder (`~/.hfai` by default), or close the app, or end the process in your operating system's task manager.

A full demo transcript from a real run is in [demos/M1-safety-layer-demo.txt](demos/M1-safety-layer-demo.txt).

## Measured results (M1, Linux, Landlock ABI 7)

- Kill switch: AI process dead **1–2 ms** after the stop was pressed, including a process set to ignore polite stop signals.
- A hung AI is stopped automatically after the timeout (30 s by default) and stays stopped until a person releases it.
- Sandboxed AI process: attempts to write a file, truncate a file, open a TCP connection and signal the guardian were all **blocked by the kernel**, and the target file was unchanged.
- Audit log: an edited entry (a "no" changed to "yes") and a deleted entry were both detected, at the exact line.
- Integrity: a one-line change to a copy of the charter was detected at start-up.

## Honest limits

These are known gaps, not hidden ones:

1. **Rules about what the AI *says*** (no deception, manipulation, hatred: H4, H5, H7, H8) are not enforced by this layer. Text checks and the evaluation suite arrive in M4. Today the AI's text is shown as-is, labelled as AI-generated.
2. **The sandbox is strongest on Linux.** On macOS only the file-size limit applies; on Windows, none of the OS restrictions apply yet. On every platform, the AI process still has no code that acts, and every action still goes through the guardian. Planned: macOS and Windows sandboxing, and a Rust version of the guardian (Phase 2).
3. **The sandbox does not yet stop the AI process *reading* files**, and does not block UDP network traffic on Linux. A read allow-list is planned.
4. **The audit log is tamper-evident, not tamper-proof.** Whoever controls the device can delete the whole log or cut entries off the end. Save the latest fingerprint (`python -m hfai.guardian status` shows it) somewhere else to catch that.
5. **Signatures:** no maintainer signing key exists yet, so today's manifests are unsigned development builds (M7 fixes this). Until then, the integrity check catches accidental or AI-made changes, but not someone who edits both a file and the manifest.
6. **Your device, your rules.** You can change anything on your own device, including the safety code. The guardian will tell you it changed (and log it if you override). That is your freedom, not a flaw.
7. **No global off switch.** The kill switch stops the copy on *this* device. In a decentralised project nobody can switch off everyone's copy, by design.
8. **Two programs writing the log at the same instant** are coordinated on Linux and macOS; on Windows this is not yet handled.
