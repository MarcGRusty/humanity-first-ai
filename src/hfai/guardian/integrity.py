"""Integrity checks: is the charter, the rules and the safety code exactly as reviewed?

Hard limit H3. The guardian fingerprints (SHA-256) every protected file at
start-up and compares the result with ``integrity/manifest.json``. If anything
differs, is missing or was added, it refuses to start and says which file.

The manifest can carry digital signatures (Ed25519) from maintainers. A
signature proves the manifest is exactly what that maintainer approved, which
protects against tampered downloads. The keys trusted for this are listed in
``integrity/trusted_keys.json``.

Honest status (Phase 1): no maintainer signing key exists yet, so manifests are
**unsigned development builds**. Signing is implemented and tested; the
founding maintainer creates a personal key in milestone M7. Until then the
check protects against accidental or AI-made changes, but not against someone
who edits both a file and the manifest. On your own device you are always free
to change anything: that is your right, and the check will tell you it changed.

Maintainers update the manifest after a reviewed change to a protected file::

    python -m hfai.guardian integrity --update
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from hfai.charter import REPO_ROOT

# Files whose exact content the guardian checks. Paths relative to the repo root.
PROTECTED_PATTERNS = (
    "CHARTER.md",
    "charter/*.toml",
    "charter/*.rules",
    "src/hfai/charter.py",
    "src/hfai/guardian/*.py",
    "src/hfai/rules/*.py",
    "src/hfai/worker/protocol.py",
)
MANIFEST_PATH = Path("integrity") / "manifest.json"
TRUSTED_KEYS_PATH = Path("integrity") / "trusted_keys.json"
MANIFEST_FORMAT = 1


def protected_files(root: Path = REPO_ROOT) -> list[str]:
    found = set()
    for pattern in PROTECTED_PATTERNS:
        for path in root.glob(pattern):
            if path.is_file():
                found.add(path.relative_to(root).as_posix())
    return sorted(found)


def compute_hashes(root: Path = REPO_ROOT) -> dict[str, str]:
    return {rel: hashlib.sha256((root / rel).read_bytes()).hexdigest() for rel in protected_files(root)}


def _signed_payload(manifest: dict) -> bytes:
    body = {"format": manifest["format"], "files": manifest["files"]}
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def build_manifest(root: Path = REPO_ROOT) -> dict:
    return {"format": MANIFEST_FORMAT, "files": compute_hashes(root), "signatures": []}


def write_manifest(root: Path = REPO_ROOT) -> Path:
    """Maintainer tool: record the current fingerprints. Drops old signatures."""
    path = root / MANIFEST_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build_manifest(root), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


# --- Signatures -----------------------------------------------------------------


def generate_keypair() -> tuple[bytes, bytes]:
    """Return (private_key, public_key) as raw bytes. Keep the private key secret."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return private, public


def key_id(public_key: bytes) -> str:
    return hashlib.sha256(public_key).hexdigest()[:16]


def sign_manifest(manifest: dict, private_key: bytes) -> dict:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.from_private_bytes(private_key)
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    signature = key.sign(_signed_payload(manifest))
    signed = dict(manifest)
    signed["signatures"] = [s for s in manifest.get("signatures", []) if s["key_id"] != key_id(public)]
    signed["signatures"].append({"key_id": key_id(public), "signature": base64.b64encode(signature).decode()})
    return signed


def verify_signatures(manifest: dict, trusted: dict) -> tuple[int, int, list[str]]:
    """Count valid signatures from trusted keys. Returns (valid, threshold, notes)."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    keys = {entry["key_id"]: entry for entry in trusted.get("keys", [])}
    threshold = int(trusted.get("threshold", 1))
    payload = _signed_payload(manifest)
    valid, notes, seen = 0, [], set()
    for sig in manifest.get("signatures", []):
        entry = keys.get(sig.get("key_id"))
        if entry is None:
            notes.append(f"signature from unknown key {sig.get('key_id')} ignored")
            continue
        if sig["key_id"] in seen:
            continue
        public = base64.b64decode(entry["public_key"])
        if key_id(public) != sig["key_id"]:
            notes.append(f"trusted key {sig['key_id']} does not match its ID")
            continue
        try:
            Ed25519PublicKey.from_public_bytes(public).verify(base64.b64decode(sig["signature"]), payload)
        except (InvalidSignature, ValueError):
            notes.append(f"INVALID signature from {entry.get('owner', sig['key_id'])}")
            continue
        seen.add(sig["key_id"])
        valid += 1
        notes.append(f"valid signature from {entry.get('owner', sig['key_id'])}")
    return valid, threshold, notes


# --- The check ----------------------------------------------------------------------


@dataclass(frozen=True)
class IntegrityReport:
    ok: bool
    changed: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    unexpected: tuple[str, ...] = ()
    signature_status: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)

    def explain(self) -> str:
        if self.ok:
            return f"Integrity check passed: charter, rules and safety code match the manifest. Signatures: {self.signature_status}."
        parts = ["INTEGRITY CHECK FAILED: protected files differ from the reviewed manifest."]
        if self.changed:
            parts.append("Changed: " + ", ".join(self.changed))
        if self.missing:
            parts.append("Missing: " + ", ".join(self.missing))
        if self.unexpected:
            parts.append("Not in the manifest: " + ", ".join(self.unexpected))
        parts.extend(self.notes)
        return " ".join(parts)


def check(root: Path = REPO_ROOT) -> IntegrityReport:
    manifest_file = root / MANIFEST_PATH
    if not manifest_file.exists():
        return IntegrityReport(False, notes=(f"No manifest at {MANIFEST_PATH}.",), signature_status="none")
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        expected = manifest["files"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return IntegrityReport(False, notes=("The manifest is unreadable.",), signature_status="none")

    actual = compute_hashes(root)
    changed = tuple(sorted(p for p in expected if p in actual and actual[p] != expected[p]))
    missing = tuple(sorted(p for p in expected if p not in actual))
    unexpected = tuple(sorted(p for p in actual if p not in expected))

    trusted_file = root / TRUSTED_KEYS_PATH
    trusted = json.loads(trusted_file.read_text(encoding="utf-8")) if trusted_file.exists() else {"keys": []}
    notes: list[str] = []
    if not trusted.get("keys"):
        signature_status = "unsigned development build (no maintainer keys yet)"
        signatures_ok = True
    else:
        try:
            valid, threshold, notes = verify_signatures(manifest, trusted)
        except ImportError:
            valid, threshold, notes = 0, 1, ["cannot check signatures: the 'cryptography' package is not installed"]
        signatures_ok = valid >= threshold
        signature_status = f"{valid} of {threshold} required maintainer signatures valid"

    ok = not (changed or missing or unexpected) and signatures_ok
    return IntegrityReport(ok, changed, missing, unexpected, signature_status, tuple(notes))
