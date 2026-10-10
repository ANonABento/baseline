"""Baseline's interventions on the client's phone (live calls, role client).

When the alert first reaches caution or high, Baseline warns the client:
    {"type":"intervention","level":"caution"|"high","message":str,"reason_id":str}
At high it also SPEAKS the message (Baseline's own voice, to the client only; the caller never
hears it) and triggers the bank's downstream actions (family alert, transfer hold).

Policy (InterventionPolicy):
- A level escalation (none -> caution, caution/none -> high) always intervenes immediately.
- At the same level, a NEW reason intervenes again, at most one per `min_gap_s` (10 s); a new
  reason arriving sooner is deferred until the gap has passed (the caller re-checks then).
- The same reason is never announced twice.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from caller.personas import BANK_SHORT, CUSTOMER

_RANK = {"none": 0, "caution": 1, "high": 2}

INTRO = f"This is Baseline, from {BANK_SHORT}."  # only on the first intervention of a call


def messages(customer_name: str = CUSTOMER.name) -> dict[str, str]:
    """reason_id -> what Baseline says (banner; spoken at high). ~3-4 s each, plus INTRO (~1.5 s) the
    first time."""
    return {
        "secret_request": f"This looks like a scam. {BANK_SHORT} will never ask for your one-time code.",
        "card_request": "This looks like a scam. Never read card numbers or PINs to a caller.",
        "gift_cards": "This looks like a scam. No real bank or agency asks for gift cards.",
        "voice_clone": f"This voice may not really be {customer_name}. Hang up and call him back.",
        "safe_account": f"This looks like a scam. {BANK_SHORT} never asks you to move money to a safe account.",
        "remote_access": "This looks like a scam. Never let a caller into your computer.",
        "government": "This looks like a scam. The IRS never calls to demand payment.",
        "generic": "This call looks like a scam. Hang up and call the number on your card.",
    }


MESSAGES = messages()


def message_for(reason_id: str, first: bool) -> str:
    m = MESSAGES.get(reason_id, MESSAGES["generic"])
    return f"{INTRO} {m}" if first else m

ACTIONS = (
    {"type": "action", "kind": "family_alert", "message": "Text sent to your trusted contact"},
    {"type": "action", "kind": "bank_hold",
     "message": f"{BANK_SHORT}: outgoing transfers held for review — linked to this flagged call"},
)

_SECRET_PATTERNS = {"otp_redirect", "credential_request"}
_GIFT_PATTERNS = {"gift_cards", "crypto_payment"}
_REMOTE_PATTERNS = {"remote_access", "overpayment_refund"}


_CODE_REASONS = {"share_code", "share_remote_code"}


def candidates(patterns: Iterable[str], client_kind: str | None, client_reason: str | None, scenario: str,
               signals: Iterable[str], client_asked: str | None = None) -> list[str]:
    """Reasons the current evidence supports, most important first (always ends with "generic").
    `client_asked`: what the caller asked for before the client read digits ("code" | "card")."""
    pats, sigs = set(patterns), set(signals)
    out: list[str] = []
    gift = bool(pats & _GIFT_PATTERNS) or client_reason == "gift_cards"
    if "safe_account" in pats:
        out.append("safe_account")
    if client_kind == "secret":
        if client_reason in _CODE_REASONS or (client_reason == "reading_digits" and client_asked == "code"):
            out.append("secret_request")
        elif gift and client_reason in ("reading_digits", "share_card", "get_card"):
            out.append("gift_cards")
        else:
            out.append("card_request")
    if gift:
        out.append("gift_cards")
    if "grandparent_bail" in pats or (scenario == "grandchild" and sigs & {"speaker", "spoof", "fraud"}):
        out.append("voice_clone")
    if pats & _SECRET_PATTERNS and "secret_request" not in out:
        out.append("secret_request")
    if pats & _REMOTE_PATTERNS:
        out.append("remote_access")
    if "government_impersonation" in pats:
        out.append("government")
    out.append("generic")
    return list(dict.fromkeys(out))


@dataclass
class Decision:
    reason_id: str | None = None  # intervene now with this reason
    defer_s: float | None = None  # or re-check after this many seconds


@dataclass
class InterventionPolicy:
    min_gap_s: float = 10.0
    level_sent: str = "none"
    last_t: float | None = None
    announced: list[str] = field(default_factory=list)

    def decide(self, level: str, reasons: list[str], t: float) -> Decision:
        if _RANK.get(level, 0) == 0 or not reasons:
            return Decision()
        new = [r for r in reasons if r not in self.announced]
        if _RANK[level] > _RANK[self.level_sent]:
            specific = [r for r in new if r != "generic"]
            return Decision(reason_id=specific[0] if specific else reasons[0])
        # same level: only a new, specific reason (never "generic" twice)
        new = [r for r in new if r != "generic"]
        if not new:
            return Decision()
        if self.last_t is not None and t - self.last_t < self.min_gap_s:
            return Decision(defer_s=round(self.min_gap_s - (t - self.last_t), 3))
        return Decision(reason_id=new[0])

    def record(self, level: str, reason_id: str, t: float) -> None:
        if _RANK.get(level, 0) > _RANK[self.level_sent]:
            self.level_sent = level
        if reason_id not in self.announced:
            self.announced.append(reason_id)
        self.last_t = t
