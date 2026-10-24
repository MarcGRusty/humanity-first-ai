"""The guardian: the safety layer, kept separate from the model.

* consent.py: no action without a person's explicit yes (H1)
* actions.py: the only actions that exist, with facts worked out by the guardian
* killswitch.py, supervisor.py: the AI runs as a separate, watched process that
  can be stopped instantly (H2)
* sandbox.py: operating-system restrictions on the AI process
* integrity.py: the charter, rules and safety code are exactly as reviewed (H3)
* audit.py: tamper-evident log of every decision and action
* core.py: ties them together

This whole package is a protected area (GOVERNANCE.md).
Command line: ``python -m hfai.guardian --help``.
"""
