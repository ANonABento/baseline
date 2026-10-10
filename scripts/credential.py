"""Issue and verify an independently verifiable session credential (Ed25519, did:key).

The credential binds: the session id, a SHA-256 of the full call report, the behavioural-signal
summary (backend/detectors/session_signals.py) and the candidate's recorded decisions, to an
issuer key. Anyone can verify it offline with only the credential file: the public key is in the
issuer DID (`did:key:z6Mk...`), the signature covers the canonical JSON of the payload.
It attests WHAT WAS OBSERVED in one simulated call. It does not attest skill, honesty or fitness.

  uv run --project backend --with cryptography python scripts/credential.py issue data/reports/<id>.json \\
        --decisions decisions.json --out cred.json [--key issuer.key]
  uv run --project backend --with cryptography python scripts/credential.py verify cred.json [--report data/reports/<id>.json]

`issuer.key` (raw 32-byte Ed25519 seed, created on first use, gitignored by data/ and *.key) is
the signing secret; never commit it. Verification needs no secret."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from detectors.session_signals import analyse  # noqa: E402

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
        "signals": analyse(report), "decisions": decisions,
        "claims": "Observed in one simulated call; signal summaries relative to the speaker's own earlier delivery; "
                  "calibration_status not_established; not a measure of skill, honesty or suitability.",
    }
    return {"payload": payload, "proof": {"alg": "Ed25519", "signature": key.sign(canonical(payload)).hex()}}


def verify(cred: dict, report: dict | None = None) -> tuple[bool, str]:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    p = cred["payload"]
    try:
        Ed25519PublicKey.from_public_bytes(public_from_did(p["issuer"])).verify(bytes.fromhex(cred["proof"]["signature"]), canonical(p))
    except (InvalidSignature, AssertionError, ValueError, KeyError):
        return False, "signature does not match payload and issuer key"
    if report is not None and hashlib.sha256(canonical(report)).hexdigest() != p["report_sha256"]:
        return False, "signature valid, but the report does not match report_sha256"
    return True, "signature valid" + (" and report matches" if report is not None else " (report not checked)")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("issue")
    i.add_argument("report"); i.add_argument("--decisions"); i.add_argument("--out", required=True)
    i.add_argument("--key", default=str(ROOT / "data" / "issuer.key"))
    v = sub.add_parser("verify")
    v.add_argument("credential"); v.add_argument("--report")
    a = ap.parse_args()
    if a.cmd == "issue":
        rep = json.loads(Path(a.report).read_text())
        dec = json.loads(Path(a.decisions).read_text()) if a.decisions else []
        Path(a.out).write_text(json.dumps(issue(rep, dec, Path(a.key)), indent=1))
        print("wrote", a.out)
    else:
        ok, msg = verify(json.loads(Path(a.credential).read_text()), json.loads(Path(a.report).read_text()) if a.report else None)
        print(("OK: " if ok else "FAIL: ") + msg)
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
