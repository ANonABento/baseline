"""Generate synthetic multi-turn calls with ElevenLabs TTS and ground-truth labels BY CONSTRUCTION (we write the scripts).

Scenarios (labels come from the script, never from a model):
  scam_*       scammer vs customer (bank / irs / tech / grandchild): per-turn scripted pressure level 1-3, scripted
               false claims (fabrication = yes), customer decision (verifies / refuses / hesitates / complies)
  benign       legitimate bank agent: pressure 0, truthful claims
  negotiation  seller states "the lowest price" while the documented private floor is lower (negotiating_bluff = yes) or
               equal (no); buyer says "very interested" with documented low private intent (mismatch = yes) or real intent (no)
Per-turn delivery label: "read" (formal, flat settings) vs "spontaneous" (disfluent text, looser settings). Customer turns also
carry an INTENDED emotion (neutral / fearful / angry / sad / happy) realised through text and ElevenLabs voice settings
(whether the audio actually conveys it is unverified: validate before training on it).

Output (data/synthetic/<run>/, gitignored under data/): calls.jsonl (brief schema), labels.csv (flat), calls/<call_id>/seg_NNN.wav +
call.wav (16 kHz mono), MANIFEST.json. Only script TEXT goes to ElevenLabs. Reads .env at the repo root (ELEVENLABS_API_KEY, optional
NEBIUS_API_KEY for --llm line writing).

  uv run --project backend python scripts/generate_synthetic_calls.py --dry-run                # no API calls: scripts + labels only
  uv run --project backend --extra ml python scripts/generate_synthetic_calls.py --calls-per-scenario 6
Limits: all-TTS data teaches TTS-style delivery; real-speech validation is still needed. Voices repeat across calls, so split by call
and check speaker/voice shortcuts (the notebook's shortcut audit)."""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SR = 16_000


def load_env() -> None:
    p = ROOT / ".env"
    if not p.exists():
        print(f"note: {p} not found (copy env.template to .env at the repo root)", file=sys.stderr)
        return
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.removeprefix("export ").split("=", 1)
        v = v.strip().strip("\"'")
        if v and not os.environ.get(k.strip()):  # a blank env var must not shadow the file
            os.environ[k.strip()] = v


# ------------------------------------------------------------------ scripts (ground truth lives here)
# (text, is_false_claim). Pressure level = list position group below.
SCAM = {
    "bank": {1: [("Hello, this is the fraud department at First Harbor Bank. We noticed unusual activity on your account.", True),
                 ("I am calling from your bank's security team about a suspicious transfer.", True)],
             2: [("To protect your money, you need to move it to a safe account right now.", True),
                 ("Our system shows the funds are at risk, I can secure them if you confirm your online banking code.", True)],
             3: [("Please do not hang up, the account will be frozen within the hour.", True),
                 ("If you tell anyone at the branch, the investigation will be compromised. Do it now.", True)]},
    "irs": {1: [("This is the Internal Revenue Service. There is a problem with your tax return.", True),
                ("We have a notice regarding unpaid taxes in your name.", True)],
            2: [("You can resolve this today by paying with gift cards, and you must stay on the line.", True),
                ("A warrant has been issued, but paying now will cancel it.", True)],
            3: [("If you do not pay in thirty minutes, officers will arrive at your home.", True),
                ("Do not speak to a lawyer, it will only make the penalties higher. Read me the card numbers.", True)]},
    "tech": {1: [("Hello, I am from Microsoft support. Your computer has sent us a virus alert.", True),
                 ("We detected unusual activity coming from your laptop.", True)],
             2: [("I need you to open the remote access tool so that I can fix it for you.", True),
                 ("Please type the code I give you so I can check that your accounts are safe.", True)],
             3: [("Do not turn off the computer, your files will be deleted if you do.", True),
                 ("There is a one time fee of three hundred dollars to remove the infection. We must do this right now.", True)]},
    "grandchild": {1: [("Grandma, it is me. I am in trouble and I need your help.", True),
                       ("Hi Grandpa, I lost my phone so this is a new number.", True)],
                   2: [("I was in a car accident and the police are here, I need money for bail today.", True),
                       ("A lawyer is going to call you, please just do what he says.", True)],
                   3: [("Please do not tell mom, I am so embarrassed. Can you wire the money right now?", True),
                       ("I cannot talk long, please send it today or I will be in real trouble.", True)]}}
BENIGN_AGENT = [("Hello, this is First Harbor Bank. How can I help you today?", False), ("I can see your balance, would you like me to read it out?", False),
                ("There is a pending charge from the grocery store on Tuesday, does that look familiar?", False),
                ("You can verify this call by phoning the number on the back of your card.", False),
                ("Is there anything else I can help you with?", False), ("Thank you for calling, have a good day.", False)]
CUSTOMER = {  # style -> (intended emotion, decision, lines)
    "calm_verifying": ("neutral", "verifies", ["Can you tell me your name and a reference number? I will call the bank back on the number I have.",
                                               "I would rather verify this myself before I do anything.", "No, I am not going to share that. I will hang up and call the branch.",
                                               "That does not sound right to me, so I will wait."]),
    "anxious_hesitant": ("fearful", "hesitates", ["Oh no, what do you mean? I am not sure what to do.", "I, I do not know, should I really do that?",
                                                  "Please, can you give me a minute, I am getting nervous.", "Is there someone else I can ask about this?"]),
    "agitated": ("angry", "refuses", ["This is ridiculous, I am not giving you anything.", "Stop pressuring me, I do not believe a word of this.",
                                      "How dare you call me and demand that, I am hanging up.", "No. Absolutely not."]),
    "compliant": ("sad", "complies", ["Okay, okay, I will do it, just tell me what to do.", "Alright, here is the number, please do not let anything happen to him.",
                                      "I will go to the store right now, I do not want any trouble.", "Yes, I will send it today."]),
    "relaxed": ("happy", "neutral_call", ["Hi, thanks for getting back to me.", "That looks familiar, yes, it was me.", "No, that is all, thank you so much.",
                                          "Great, that is helpful, have a good day."])}
BENIGN_STYLES = ["relaxed", "calm_verifying"]
FILLERS = ["um,", "uh,", "I mean,", "you know,", "well,", "sort of,"]
EMO_SETTINGS = {"neutral": dict(stability=0.6, style=0.1, speed=1.0), "fearful": dict(stability=0.3, style=0.5, speed=1.1),
                "angry": dict(stability=0.25, style=0.7, speed=1.1), "sad": dict(stability=0.5, style=0.3, speed=0.9),
                "happy": dict(stability=0.35, style=0.6, speed=1.05)}
EMO8 = ["neutral", "calm", "happy", "sad", "angry", "fearful", "disgust", "surprised"]  # same labels as RAVDESS / the notebook
V3_TAGS = {"neutral": "", "calm": "[calmly]", "happy": "[cheerfully]", "sad": "[sadly]", "angry": "[angry]", "fearful": "[fearfully, voice trembling]",
           "disgust": "[disgusted]", "surprised": "[surprised, gasps]"}
V3_MODEL = "eleven_v3"  # the only ElevenLabs model that renders audio tags; stability must be 0.0 / 0.5 / 1.0
CORPUS_SENTENCES = ["The meeting is on Thursday at three o'clock.", "I put the package on the kitchen table.", "She told me the bank closes at five.",
                    "We need to talk about the account.", "He said the number was on the back of the card.", "The car is parked outside the office.",
                    "I will call you back tomorrow morning.", "There is a letter for you on the desk.", "They moved the appointment to next week.",
                    "My phone has been ringing all afternoon.", "The report is ready if you want to see it.", "I did not expect to hear from you today."]
READ_SETTINGS = dict(stability=0.85, style=0.0, speed=1.0)
SPONT_SETTINGS = dict(stability=0.35, style=0.35, speed=1.0)
KNOWN_VOICES = {"roger": "CwhRBWXzGAHq8TQ4Fs17", "callum": "N2lVS1w4EtoT3dr4eOWO", "george": "JBFqnCBsd6RMkjVDRZzb", "sarah": "EXAVITQu4vr4xnSDxMaL",
                "clone_kevin": "kHe5D7QBSu8PKLzFC8Hz"}
SCAMMER_VOICES, CUSTOMER_VOICES = ["roger", "callum", "george", "clone_kevin"], ["sarah"]


def spontaneous(text: str, rng: random.Random) -> str:
    words = text.split(" ")
    out = []
    for i, w in enumerate(words):
        if i > 0 and rng.random() < 0.08:
            out.append(rng.choice(FILLERS))
        out.append(w)
    return " ".join(out)


def build_call(call_id: str, kind: str, rng: random.Random) -> dict:
    turns, events = [], []
    if kind.startswith("scam_"):
        scen = kind[5:]
        style = rng.choice(["calm_verifying", "anxious_hesitant", "agitated", "compliant"])
        levels = [1, 1, 2, 2, 3, 3]
        lines = [(lv, *rng.choice(SCAM[scen][lv])) for lv in levels]
        cust = CUSTOMER[style]; used = rng.sample(cust[2], k=min(len(cust[2]), len(lines)))
        for k, (lv, text, false) in enumerate(lines):
            turns.append(dict(role="scammer", text=text, pressure_level=lv, fabrication="yes" if false else "no"))
            turns.append(dict(role="customer", text=used[k % len(used)], emotion=cust[0], customer_style=style))
        events.append(dict(target="customer_decision", ground_truth=cust[1], ground_truth_source="scripted"))
    elif kind == "benign":
        style = rng.choice(BENIGN_STYLES); cust = CUSTOMER[style]
        for k, (text, false) in enumerate(BENIGN_AGENT):
            turns.append(dict(role="agent", text=text, pressure_level=0, fabrication="no"))
            turns.append(dict(role="customer", text=cust[2][k % len(cust[2])], emotion=cust[0], customer_style=style))
    else:  # negotiation
        item = rng.choice(["used laptop", "sofa", "mountain bike", "camera lens"]); stated = rng.choice([400, 650, 900, 1200])
        bluff = rng.random() < 0.5; floor = int(stated * 0.85) if bluff else stated
        feigned = rng.random() < 0.5; budget = int(stated * (0.6 if feigned else 1.0))
        turns = [dict(role="buyer", text=f"Hi, I saw your listing for the {item}. Is it still available?"),
                 dict(role="seller", text="Yes it is, I am asking " + str(int(stated * 1.15)) + " dollars."),
                 dict(role="buyer", text=("This is great, I am very interested, I would love to buy it." if feigned else f"I can pay up to {budget} dollars if it is in good shape."),
                      mismatch="yes" if feigned else "no"),
                 dict(role="seller", text=f"That is the lowest price I can go, {stated} dollars, I cannot take less.", bluff="yes" if bluff else "no"),
                 dict(role="buyer", text=("Sounds good, I will think about it and get back to you." if feigned else "Okay, that works for me, I will take it."), mismatch="yes" if feigned else "no")]
        events.append(dict(target="negotiating_bluff", ground_truth="yes" if bluff else "no", ground_truth_source=f"scripted_private_limits (stated {stated}, private floor {floor})"))
        events.append(dict(target="interest_vs_intent_mismatch", ground_truth="yes" if feigned else "no", ground_truth_source=f"scripted_private_intent (budget {budget})"))
    # per-call delivery per role: read-like or spontaneous (independent of voice and label)
    delivery = {r: rng.choice(["read", "spontaneous"]) for r in {t["role"] for t in turns}}
    for t in turns:
        t["delivery"] = delivery[t["role"]]
        if t["delivery"] == "spontaneous": t["text"] = spontaneous(t["text"], rng)
    return dict(call_id=call_id, scenario=kind, turns=turns, events=events)


def llm_expand(texts: list[str], n: int) -> list[str]:
    """Optional: ask the LLM for paraphrases of scripted lines (same meaning, same false/true status). Falls back silently."""
    key = os.environ.get("NEBIUS_API_KEY")
    if not key: return texts
    try:
        body = {"model": os.environ.get("LLM_MODEL") or "openai/gpt-oss-120b", "max_tokens": 600,
                "messages": [{"role": "user", "content": "Rewrite each line in different words, same meaning and tone, one per line, no numbering:\n" + "\n".join(texts)}]}
        req = urllib.request.Request((os.environ.get("LLM_BASE_URL") or "https://api.tokenfactory.nebius.com/v1/").rstrip("/") + "/chat/completions",
                                     data=json.dumps(body).encode(), headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        out = json.loads(urllib.request.urlopen(req, timeout=30).read())["choices"][0]["message"]["content"].strip().splitlines()
        return out if len(out) == len(texts) else texts
    except Exception:  # noqa: BLE001
        return texts


def tts(key: str, voice_id: str, text: str, model: str, settings: dict) -> np.ndarray:
    if model == V3_MODEL:  # v3: audio tags are in the text; only stability is accepted (0.0 creative / 0.5 natural / 1.0 robust)
        settings = {"stability": settings.get("stability", 0.0)}
    req = urllib.request.Request(f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=pcm_16000",
                                 data=json.dumps({"text": text, "model_id": model, "voice_settings": settings}).encode(),
                                 headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/pcm"})
    return np.frombuffer(urllib.request.urlopen(req, timeout=90).read(), "<i2").astype(np.float32) / 32768.0


def main() -> None:
    load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--calls-per-scenario", type=int, default=int(os.environ.get("SYNTH_CALLS_PER_SCENARIO", 6)))
    ap.add_argument("--model", default=os.environ.get("SYNTH_MODEL", "eleven_flash_v2_5"))
    ap.add_argument("--out", default=os.environ.get("SYNTH_OUT_DIR", "data/synthetic"))
    ap.add_argument("--scenarios", default="scam_bank,scam_irs,scam_tech,scam_grandchild,benign,negotiation")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--max-chars", type=int, default=60_000, help="stop before sending more than this many characters to ElevenLabs")
    ap.add_argument("--dry-run", action="store_true", help="write scripts and labels only; no API calls, no audio")
    ap.add_argument("--llm", action="store_true", help="paraphrase scripted lines with the Nebius LLM (labels unchanged)")
    ap.add_argument("--emotions", dest="emotions", action="store_true", default=True, help="render non-neutral customer / pressure-3 scammer turns with eleven_v3 audio tags (default on)")
    ap.add_argument("--no-emotions", dest="emotions", action="store_false", help="use only voice settings (flash/multilingual) for emotion")
    ap.add_argument("--emotion-corpus", type=int, default=0, metavar="N", help="also write N sentences x 8 emotions x voices as single-turn clips with eleven_v3 (acted, labelled by construction)")
    a = ap.parse_args()
    rng = random.Random(a.seed)
    key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not a.dry_run and not key: sys.exit("ELEVENLABS_API_KEY is empty: fill it in .env (cp env.template .env) or use --dry-run")
    voices = dict(KNOWN_VOICES)
    scammer_voices = list(SCAMMER_VOICES)
    if not a.dry_run:
        try:
            req = urllib.request.Request("https://api.elevenlabs.io/v1/voices", headers={"xi-api-key": key})
            for v in json.loads(urllib.request.urlopen(req, timeout=30).read())["voices"]:
                if v.get("category") == "premade": voices.setdefault(v["name"].split(" - ")[0].lower(), v["voice_id"])
            listed = {v["voice_id"] for v in json.loads(urllib.request.urlopen(req, timeout=30).read())["voices"]}
            for name in [n for n in scammer_voices if voices[n] not in listed]:  # e.g. the clone lives in another account
                print(f"voice '{name}' ({voices[name]}) is not in this ElevenLabs account: skipping it"); scammer_voices.remove(name)
        except Exception as e:  # noqa: BLE001
            print("voice listing unavailable (", e, "): using the known voice ids")
    cust_voices = [v for v in ("sarah", "laura", "charlie") if v in voices] or CUSTOMER_VOICES
    run = Path(a.out) if Path(a.out).is_absolute() else ROOT / a.out
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"); run = run / stamp; (run / "calls").mkdir(parents=True)
    chars, calls_out, flat = 0, [], []
    n = 0
    for kind in a.scenarios.split(","):
        for _ in range(a.calls_per_scenario):
            n += 1; call = build_call(f"syn_{n:04d}", kind, rng)
            if a.llm:
                for t, new in zip(call["turns"], llm_expand([t["text"] for t in call["turns"]], 1)): t["text"] = new
            roles = sorted({t["role"] for t in call["turns"]})
            vmap = {r: (rng.choice(scammer_voices) if r in ("scammer", "seller") else (rng.choice(cust_voices) if r in ("customer", "buyer") else rng.choice(["roger", "george", "callum"]))) for r in roles}
            cdir = run / "calls" / call["call_id"]; cdir.mkdir(); t_now, segs, wavs = 0.0, [], []
            for k, t in enumerate(call["turns"]):
                if not a.dry_run:
                    if chars + len(t["text"]) > a.max_chars: print("max-chars reached, stopping"); break
                    emo = t.get("emotion")
                    mdl, text_in = a.model, t["text"]
                    if a.emotions and emo and emo != "neutral" and t["role"] in ("customer", "buyer") and t["delivery"] == "spontaneous":
                        mdl, text_in = V3_MODEL, f"{V3_TAGS[emo]} {t['text']}"
                    elif a.emotions and t["role"] == "scammer" and t.get("pressure_level") == 3 and t["delivery"] == "spontaneous":
                        mdl, text_in, t["emotion"] = V3_MODEL, f"{V3_TAGS['angry']} {t['text']}", "angry"
                    st = dict(EMO_SETTINGS[emo]) if (emo and t["role"] in ("customer", "buyer") and t["delivery"] == "spontaneous") else dict(READ_SETTINGS if t["delivery"] == "read" else SPONT_SETTINGS)
                    st.update(similarity_boost=0.75)
                    audio = tts(key, voices[vmap[t["role"]]], text_in, mdl, st); chars += len(text_in)
                    import soundfile as sf
                    sf.write(cdir / f"seg_{k:03d}.wav", audio, SR)
                    gap = {"anxious_hesitant": 1.8, "calm_verifying": 0.7, "agitated": 0.25, "compliant": 1.0}.get(t.get("customer_style", ""), 0.6) if t["role"] in ("customer", "buyer") else 0.5
                    wavs += [np.zeros(int(gap * SR), np.float32), audio]; t_now += gap; dur = len(audio) / SR
                else:
                    mdl, dur, st, gap = None, len(t["text"].split()) / 2.6, {}, 0.5
                emo = t.get("emotion")
                segs.append(dict(segment_id=f"seg_{k:03d}", speaker_id=f"{vmap[t['role']]}_{t['role']}", audio_file=f"calls/{call['call_id']}/seg_{k:03d}.wav", start_seconds=round(t_now, 2),
                                 end_seconds=round(t_now + dur, 2), text=t["text"], voice_settings=st, tts_model=(mdl if not a.dry_run else None),
                                 annotations=dict(role=t["role"], delivery_mode=t["delivery"], pressure_level=t.get("pressure_level"), intended_emotion=emo,
                                                  fabrication=t.get("fabrication"), negotiating_bluff=t.get("bluff"), mismatch=t.get("mismatch"), customer_style=t.get("customer_style"),
                                                  label_source="scripted")))
                t_now += dur
            if wavs and not a.dry_run:
                import soundfile as sf
                sf.write(cdir / "call.wav", np.concatenate(wavs), SR)
            calls_out.append(dict(call_id=call["call_id"], scenario=call["scenario"], voices=vmap, segments=segs, events=call["events"], split="train"))
            for s in segs: flat.append(dict(call_id=call["call_id"], scenario=call["scenario"], **{k: s[k] for k in ("segment_id", "speaker_id", "audio_file", "start_seconds", "end_seconds", "text")}, **s["annotations"]))
    if a.emotion_corpus:  # acted emotion clips: same neutral sentence in every emotion, several voices; one single-turn "call" each
        corpus_voices = [v for v in ("roger", "george", "callum", "sarah", "laura", "charlie") if v in voices and (v not in SCAMMER_VOICES or v in scammer_voices)]
        sents = rng.sample(CORPUS_SENTENCES, k=min(a.emotion_corpus, len(CORPUS_SENTENCES))); import soundfile as sf
        for vi, vname in enumerate(corpus_voices):
            for si, sent in enumerate(sents):
                for emo in EMO8:
                    cid = f"emo_{vname}_{si:02d}_{emo}"; cdir = run / "calls" / cid; cdir.mkdir(); text_in = f"{V3_TAGS[emo]} {sent}".strip()
                    if not a.dry_run:
                        if chars + len(text_in) > a.max_chars: print("max-chars reached, stopping"); break
                        audio = tts(key, voices[vname], text_in, V3_MODEL, dict(stability=0.0)); chars += len(text_in); sf.write(cdir / "seg_000.wav", audio, SR); sf.write(cdir / "call.wav", audio, SR)
                        dur = len(audio) / SR
                    else:
                        dur = len(sent.split()) / 2.6
                    ann = dict(role="speaker", delivery_mode="acted", pressure_level=None, intended_emotion=emo, fabrication=None, negotiating_bluff=None, mismatch=None, customer_style=None, label_source="scripted_v3_audio_tag")
                    seg = dict(segment_id="seg_000", speaker_id=f"{vname}_speaker", audio_file=f"calls/{cid}/seg_000.wav", start_seconds=0.0, end_seconds=round(dur, 2), text=sent, voice_settings={}, tts_model=V3_MODEL, annotations=ann)
                    calls_out.append(dict(call_id=cid, scenario="emotion_corpus", voices={"speaker": vname}, segments=[seg], events=[], split="train"))
                    flat.append(dict(call_id=cid, scenario="emotion_corpus", **{k: seg[k] for k in ("segment_id", "speaker_id", "audio_file", "start_seconds", "end_seconds", "text")}, **ann))
    idx = list(range(len(calls_out))); random.Random(a.seed + 1).shuffle(idx)
    for r, i in enumerate(idx): calls_out[i]["split"] = "test" if r < max(1, len(idx) // 7) else ("val" if r < 2 * max(1, len(idx) // 7) else "train")
    (run / "calls.jsonl").write_text("\n".join(json.dumps(c) for c in calls_out))
    with (run / "labels.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(flat[0].keys())); w.writeheader(); w.writerows(flat)
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    (run / "MANIFEST.json").write_text(json.dumps(dict(timestamp=stamp, git_sha=sha, seed=a.seed, model=a.model, dry_run=a.dry_run, llm_paraphrase=a.llm, n_calls=len(calls_out),
                                                       n_segments=len(flat), characters_sent_to_elevenlabs=chars, voices={k: v for k, v in voices.items() if k in set(SCAMMER_VOICES + cust_voices + ["roger", "george", "callum"])}), indent=1))
    print(f"wrote {len(calls_out)} calls, {len(flat)} segments to {run}; characters sent to ElevenLabs: {chars}")


if __name__ == "__main__":
    main()
