"""End-of-call report: persisted as data/reports/<session_id>.json (gitignored).

Shape (stable; GET /api/report/{id} returns it verbatim):
{
  "id", "created_at" (ISO UTC), "ended_reason": "hangup"|"timeout"|"error",
  "meta": {role, scenario, scenario_label, voice, tts, llm: {provider, model}, persona: {label, summary},
           customer: {id, name, account_mask, enrolled}, analyzed_channel: "ai"|"visitor", requested: {...}},
  "durations": {queue_wait_s, call_s},
  "transcript": [{utterance_id, speaker, analyzed, text, t_start, t_end, latency_ms}],
  "signals": [SignalEvent...  + "t" (s since call start)],
  "trust": [TrustEvent... + "t"],
  "alerts": [AlertEvent... + "t"],
  "verdict": {level, label, trust, fired, signals_fired_ever, reasons, suggested_action, caught: bool,
              final_signals: {name: {score, confidence, reason}}},
  "fraud_evidence": [{id, name, severity, quote, utterance_id, source, suggested_agent_action, say_this?}],
  "latencies": {turns: [{turn, source, visitor_end_to_first_audio_ms, speech_end_to_first_audio_ms?, stt_ms?,
                         llm_first_sentence_ms, tts_first_audio_ms}],
                mean_turn_ms, p50_turn_ms, max_turn_ms, pipeline: [per-utterance timings]},
  "errors": [str]
}
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

_ID = re.compile(r"^[A-Za-z0-9_-]{4,64}$")
VERDICT_LABELS = {"none": "No alert", "caution": "Suspicious", "high": "Fraud likely"}


def valid_report_id(rid: str) -> bool:
    return bool(_ID.match(rid or ""))


def save_report(reports_dir: Path, report: dict) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"{report['id']}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)
    return path


def load_report(reports_dir: Path, rid: str) -> dict | None:
    if not valid_report_id(rid):
        return None
    path = reports_dir / f"{rid}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.warning("unreadable report %s", path)
        return None


def summarize(report: dict) -> dict:
    meta, verdict = report.get("meta", {}), report.get("verdict", {})
    return {
        "id": report.get("id"),
        "created_at": report.get("created_at"),
        "role": meta.get("role"),
        "scenario": meta.get("scenario"),
        "voice": meta.get("voice"),
        "ended_reason": report.get("ended_reason"),
        "call_s": report.get("durations", {}).get("call_s"),
        "level": verdict.get("level"),
        "label": verdict.get("label"),
        "trust": verdict.get("trust"),
        "caught": verdict.get("caught"),
        "turns": len(report.get("transcript", [])),
    }


def list_reports(reports_dir: Path, limit: int = 20) -> list[dict]:
    if not reports_dir.is_dir():
        return []
    files = sorted(reports_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    out = []
    for p in files[: max(0, limit)]:
        r = load_report(reports_dir, p.stem)
        if r is not None:
            out.append(summarize(r))
    return out
