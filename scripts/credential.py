"""CLI for backend/credential.py (issue / verify an Ed25519 did:key simulation credential).

  uv run --project backend python scripts/credential.py issue data/reports/<id>.json --out cred.json
  uv run --project backend python scripts/credential.py verify cred.json [--report data/reports/<id>.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from credential import issue, verify  # noqa: E402


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
        dec = json.loads(Path(a.decisions).read_text()) if a.decisions else rep.get("behaviour", {}).get("decision_events", [])
        Path(a.out).write_text(json.dumps(issue(rep, dec, Path(a.key)), indent=1))
        print("wrote", a.out)
    else:
        ok, msg = verify(json.loads(Path(a.credential).read_text()), json.loads(Path(a.report).read_text()) if a.report else None)
        print(("OK: " if ok else "FAIL: ") + msg)
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
