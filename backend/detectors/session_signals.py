"""Session-level behavioural signals from a finished call (V-owned, pure functions, no models).

Input: a call report (`backend/caller/report.py` shape: `transcript` with speaker/analyzed/t_start/
t_end/text, `signals` with the prosody `details` per utterance). Output: observations about HOW the
analysed speaker delivered under the scenario, relative to their own earlier delivery:

  tone_drift            slope of pitch z and of loudness z across the call (z per minute)
  speech_rate           words per second per turn (from transcript timing) and its trend
  hesitation            pause fraction, filler words per 100 words
  response_latency      seconds from the other party finishing to the analysed speaker starting
  recovery_latency      seconds from the largest delivery change until delivery is back within the
                        speaker's own range ("de-escalation latency"); null if it never returns

These are signal summaries. They are NOT a measure of skill, honesty or suitability, and
calibration against any outcome is NOT established (`calibration_status`). Small N per call.
"""

from __future__ import annotations

import re

import numpy as np

HEDGES = re.compile(r"\b(maybe|perhaps|i think|i guess|sort of|kind of|probably|not sure)\b", re.I)
VERIFY = re.compile(r"\b(verify|verification|call (you|them|him|her) back|number on file|who is (this|calling)|can i confirm|prove|reference number|official)\b", re.I)
REFUSE = re.compile(r"\b(no\b(?!\s+(problem|worries|rush|trouble|issue))|not going to|won't|will not|i refuse|hang up|hanging up|not giving|don't share|do not share)\b", re.I)
COMPLY = re.compile(r"\b(here (is|are)|my (card|account|pin|social|code) (number )?is|i('ll| will) (send|transfer|wire|read)|okay,? (i'll|let me) (send|transfer|wire|read))\b", re.I)
FILLERS = re.compile(r"\b(um+|uh+|er+|erm|hmm+|you know|i mean|like)\b", re.I)
Z_RECOVER = 2.5  # same threshold as voice_state.Z_FIRE (kept literal: report consumers need no backend import)


ESCALATE = re.compile(r"\b(escalat\w*|supervisor|team lead|my manager|senior|compliance|fraud team|specialist)\b", re.I)
ALTERNATIVE = re.compile(r"\b(what i can do|what we can do|instead|alternatively|another option|in the meantime|next step|i can offer)\b", re.I)
OVERPROMISE = re.compile(r"\b(i promise|i guarantee|guaranteed|definitely (will|be)|100 ?%|no problem at all|consider it done|it will be (there|done))\b", re.I)


def decision_tags(text: str) -> list[str]:
    """Keyword-based decision phrases in one turn's STT text (also used live, so UI and report agree)."""
    return [ev for ev, rx in (("verification_requested", VERIFY), ("refused", REFUSE), ("complied_phrase", COMPLY),
                              ("escalated", ESCALATE), ("offered_alternative", ALTERNATIVE), ("overpromised", OVERPROMISE))
            if rx.search(text)]


def _prosody_by_utt(report: dict) -> dict[int, dict]:
    return {s["utterance_id"]: s["details"] for s in report.get("signals", []) if s.get("signal") == "prosody"}


def _slope_per_min(t: list[float], y: list[float]) -> float | None:
    if len(t) < 3 or np.ptp(t) < 5.0:
        return None
    return round(float(np.polyfit(t, y, 1)[0] * 60.0), 3)


def analyse(report: dict, pressure: dict[int, int] | None = None) -> dict:
    """`pressure` (optional): interviewer utterance_id -> scripted pressure level (1..3). Pressure is the
    scenario's own manipulation (known, not inferred), so delivery change by applied level needs no stress label.
    Every analysed turn counts toward the level of the most recent interviewer turn before it."""
    turns = [u for u in report.get("transcript", []) if u.get("analyzed")]
    allturns = sorted(report.get("transcript", []), key=lambda u: u["t_start"])
    pros = _prosody_by_utt(report)
    rows, resp = [], []
    for u in turns:
        words = len(u["text"].split())
        dur = max(u["t_end"] - u["t_start"], 1e-3)
        d = pros.get(u["utterance_id"], {})
        z = d.get("z") or {}
        prev = [o for o in allturns if o["t_end"] <= u["t_start"]]
        if prev and not prev[-1].get("analyzed"):  # only when the other party spoke immediately before
            resp.append(round(u["t_start"] - prev[-1]["t_end"], 2))
        rows.append({"t": u["t_start"], "t_end": u["t_end"], "wps": words / dur, "words": words,
                     "fillers": len(FILLERS.findall(u["text"])), "pause_frac": (d.get("features") or {}).get("pause_frac"),
                     "z_f0": z.get("f0_median_st"), "z_rms": z.get("rms_db"), "z": z,
                     "change": d.get("delivery_change"), "status": d.get("status")})
    ok = [r for r in rows if r["status"] == "ok" and r["z"]]
    t = [r["t"] for r in ok]
    words = sum(r["words"] for r in rows)
    out = {
        "n_turns_analysed": len(rows), "n_turns_with_baseline": len(ok), "calibration_status": "not_established",
        "tone_drift": {"pitch_z_per_min": _slope_per_min(t, [r["z_f0"] for r in ok]),
                       "loudness_z_per_min": _slope_per_min(t, [r["z_rms"] for r in ok]),
                       "max_abs_z": round(max((max(abs(v) for v in r["z"].values()) for r in ok), default=0.0), 2)},
        "speech_rate": {"words_per_s_mean": round(float(np.mean([r["wps"] for r in rows])), 2) if rows else None,
                        "words_per_s_trend_per_min": _slope_per_min([r["t"] for r in rows], [r["wps"] for r in rows])},
        "hesitation": {"fillers_per_100_words": round(100.0 * sum(r["fillers"] for r in rows) / words, 1) if words else None,
                       "pause_frac_mean": round(float(np.mean([r["pause_frac"] for r in rows if r["pause_frac"] is not None])), 3)
                       if any(r["pause_frac"] is not None for r in rows) else None},
        "response_latency_s": {"mean": round(float(np.mean(resp)), 2) if resp else None,
                               "max": max(resp) if resp else None, "n": len(resp)},
    }
    n = max(len(rows), 1)
    cand_dur = sum(r["t_end"] - r["t"] for r in rows)
    other = [u for u in allturns if not u.get("analyzed")]
    other_dur = sum(u["t_end"] - u["t_start"] for u in other)
    talk_over = sum(1 for u in turns if any(o["t_start"] < u["t_start"] < o["t_end"] for o in other))
    texts = [u["text"] for u in turns]
    out["interaction"] = {
        "talk_over_count": talk_over, "talk_time_share": round(cand_dur / (cand_dur + other_dur), 2) if cand_dur + other_dur else None,
        "mean_turn_s": round(cand_dur / n, 1) if rows else None,
        "hedges_per_100_words": round(100.0 * sum(len(HEDGES.findall(x)) for x in texts) / words, 1) if words else None,
        "verification_attempts": sum(len(VERIFY.findall(x)) > 0 for x in texts),
        "escalations": sum(len(ESCALATE.findall(x)) > 0 for x in texts),
        "alternatives_offered": sum(len(ALTERNATIVE.findall(x)) > 0 for x in texts),
        "overpromises": sum(len(OVERPROMISE.findall(x)) > 0 for x in texts),
        "refusals": sum(len(REFUSE.findall(x)) > 0 for x in texts),
        "compliance_phrases": sum(len(COMPLY.findall(x)) > 0 for x in texts),
        "note": "keyword-based counts on STT text; a model-based decision tagger can replace them",
    }
    out["decision_events"] = [{"t": round(u["t_start"], 1), "utterance_id": u["utterance_id"], "event": ev}
                              for u in turns for ev in decision_tags(u["text"])]
    if pressure:
        by: dict[int, list[float]] = {}
        for u in turns:
            prev = [o for o in allturns if o["t_end"] <= u["t_start"] and not o.get("analyzed")]
            d = pros.get(u["utterance_id"], {})
            if prev and prev[-1]["utterance_id"] in pressure and d.get("z"):
                by.setdefault(pressure[prev[-1]["utterance_id"]], []).append(max(abs(v) for v in d["z"].values()))
        out["delivery_change_by_pressure_level"] = {str(k): {"mean_max_abs_z": round(float(np.mean(v)), 2), "n": len(v)} for k, v in sorted(by.items())}
    peak = max((r for r in ok if r["change"] is not None), key=lambda r: max(abs(v) for v in r["z"].values()), default=None)
    rec = None
    if peak is not None and max(abs(v) for v in peak["z"].values()) >= Z_RECOVER:
        later = [r for r in ok if r["t"] > peak["t_end"] and max(abs(v) for v in r["z"].values()) < Z_RECOVER]
        rec = {"peak_at_s": round(peak["t_end"], 1), "latency_s": round(later[0]["t"] - peak["t_end"], 1) if later else None,
               "status": "recovered" if later else "not_recovered_in_call"}
    out["recovery_latency"] = rec or {"status": "no_peak_over_threshold"}
    return out
