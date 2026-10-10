"""Issue and verify an independently verifiable session credential (Ed25519, did:key).

The credential binds: the session id, a SHA-256 of the full call report, the behavioural-signal
summary (backend/detectors/session_signals.py) and the candidate's recorded decisions, to an
issuer key. Anyone can verify it offline with only the credential file: the public key is in the
issuer DID (`did:key:z6Mk...`), the signature covers the canonical JSON of the payload.
It attests WHAT WAS OBSERVED in one simulated call. It does not attest skill, honesty or fitness.

  uv run --project backend python scripts/credential.py issue data/reports/<id>.json \\
        --decisions decisions.json --out cred.json [--key issuer.key]
  uv run --project backend python scripts/credential.py verify cred.json [--report data/reports/<id>.json]

`issuer.key` (raw 32-byte Ed25519 seed, created on first use, gitignored via *.key) is
the signing secret; never commit it. Verification needs no secret."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from caller.report import load_report, valid_report_id
from detectors.session_signals import analyse

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def b58encode(b: bytes) -> str:
    n, out = int.from_bytes(b, "big"), ""
    while n:
        n, r = divmod(n, 58)
        out = B58[r] + out
    return "1" * (len(b) - len(b.lstrip(b"\0"))) + out


def b58decode(s: str) -> bytes:
    n = 0
    for c in s:
        n = n * 58 + B58.index(c)
    body = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return b"\0" * (len(s) - len(s.lstrip("1"))) + body


def did_from_public(pub: bytes) -> str:
    return "did:key:z" + b58encode(b"\xed\x01" + pub)


def public_from_did(did: str) -> bytes:
    raw = b58decode(did.removeprefix("did:key:z"))
    assert raw[:2] == b"\xed\x01" and len(raw) == 34, "not an Ed25519 did:key"
    return raw[2:]


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def load_key(path: Path):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    if path.exists():
        return Ed25519PrivateKey.from_private_bytes(path.read_bytes())
    from cryptography.hazmat.primitives import serialization

    k = Ed25519PrivateKey.generate()
    path.write_bytes(k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()))
    path.chmod(0o600)
    return k


def issue(report: dict, decisions: list[dict], key_path: Path) -> dict:
    from cryptography.hazmat.primitives import serialization

    key = load_key(key_path)
    pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    payload = {
        "type": "BaselineSimulationCredential", "version": 1, "issuer": did_from_public(pub),
        "issued_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "session_id": report["id"], "report_sha256": hashlib.sha256(canonical(report)).hexdigest(),
        "signals": report.get("behaviour") or analyse(report), "decisions": decisions,
        "claims": "Observed in one simulated call; signal summaries relative to the speaker's own earlier delivery; "
                  "calibration_status not_established; not a measure of skill, honesty or suitability.",
    }
    text = canonical(payload).decode()  # the exact signed text: verifiers in any language check this string
    return {"payload": payload, "proof": {"alg": "Ed25519", "signed_text": text, "signature": key.sign(text.encode()).hex()}}


def verify(cred: dict, report: dict | None = None) -> tuple[bool, str]:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    p = cred["payload"]
    try:
        text = cred["proof"]["signed_text"]
        Ed25519PublicKey.from_public_bytes(public_from_did(p["issuer"])).verify(bytes.fromhex(cred["proof"]["signature"]), text.encode())
        if json.loads(text) != p:
            return False, "payload differs from the signed text"
    except (InvalidSignature, AssertionError, ValueError, KeyError):
        return False, "signature does not match payload and issuer key"
    if report is not None and hashlib.sha256(canonical(report)).hexdigest() != p["report_sha256"]:
        return False, "signature valid, but the report does not match report_sha256"
    return True, "signature valid" + (" and report matches" if report is not None else " (report not checked)")


def issuer_did(key_path: Path) -> str:
    """Public issuer identity (creates the key on first use). Publish this so verifiers can pin the issuer."""
    from cryptography.hazmat.primitives import serialization

    pub = load_key(key_path).public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return did_from_public(pub)


def credential_path(reports_dir: Path, rid: str) -> Path:
    return reports_dir / "credentials" / f"{rid}.json"


def issue_for_report(reports_dir: Path, rid: str, key_path: Path) -> dict | None:
    """Sign the SAVED report (so the hash matches the file a verifier receives) and store the credential."""
    report = load_report(reports_dir, rid)
    if report is None:
        return None
    cred = issue(report, report.get("behaviour", {}).get("decision_events", []), key_path)
    path = credential_path(reports_dir, rid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cred, indent=1), encoding="utf-8")
    return cred


def load_credential(reports_dir: Path, rid: str) -> dict | None:
    if not valid_report_id(rid):
        return None
    path = credential_path(reports_dir, rid)
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    except (OSError, json.JSONDecodeError):
        return None
