# Task: stop the AI caller from answering while the visitor is still talking

**Owner:** next agent · **Size:** about 1 hour · **Deadline:** submission at 9:00 AM, Oct 10

## Bug (from live testing)
In a live call, if the visitor pauses mid-thought for about 0.5–0.8 s, the AI replies to the first half of what they said.
Example: the visitor says "Yeah, I did get a text, but…", pauses, and the AI is already talking.

## How it works today (`backend/caller/live_call.py`)
- `feed_mic()` sends mic audio to `self.turn_vad`, the AI's own segmenter, built in `backend/segmenter.py`.
  - The segmenter closes an utterance after `vad_hangover_ms` of silence (**500 ms**, `backend/settings.py:27`).
  - For role `client`, each closed segment goes to `stt_q`, then `_stt_worker`, which pushes a `VisitorTurn` onto `turn_q`.
  - For role `scammer`, transcripts come from `CallPipeline` (`self.pipe`) instead, through `_on_pipe_event`.
- `_turn_worker()` takes a turn from the queue. It waits up to 4 s while `visitor_speaking` is true, merges any queued turns, then calls `_run_ai_turn_merging()`.
- `_run_ai_turn_merging()` (commit ad090fb) drops the reply if another turn arrives **before any audio is heard**.
- `barge_in()` cancels the AI if the visitor talks over it for `barge_in_ms` (350 ms).

So the gap is the endpointing itself: 500 ms of silence counts as "finished". Speech-to-text (STT) plus the language model (LLM) plus text-to-speech (TTS) are fast enough that the reply starts playing before the visitor resumes.

## Fix
1. **Longer hold before the AI replies.** Add a setting `turn_end_silence_ms`, default about 800.
   - After a visitor turn arrives, `_turn_worker` waits until the visitor has been silent this long in total before generating.
   - If they resume, wait for the next turn and merge.
   - Don't raise `vad_hangover_ms` globally: `CallPipeline` analysis segmentation also uses it.
   - Track `last_visitor_speech_at` (monotonic) in `feed_mic` while `in_speech`.
2. **Hold longer when the words sound unfinished.** Add `looks_unfinished(text) -> bool`.
   - Return true when the text ends with a conjunction or filler: and, but, so, because, or, um, uh, like, the, a, my, I, to, if, that.
   - Also true for a trailing comma or dash, or a fragment of one or two words.
   - Short complete answers count as finished: yes, no, okay, hello, hi, who is this, sure, what.
   - When unfinished, add `turn_unfinished_extra_ms` (default about 1100) to the hold.
3. Complete sentences ("No.", "Who is this?") should still get a reply about as fast as today, at most +300 ms.
4. Put every threshold in `backend/settings.py` and make each overridable by an environment variable. Add them to `.env.example`.
5. Latency metrics: `VisitorTurn`/turn stats report `speech_end_to_first_audio_ms` using `vad_hangover_ms`. Keep that honest by including the new hold.

## Tests
- Unit-test `looks_unfinished` with roughly 15 cases.
- Add a hold/merge test in the style of `tests/test_live.py`:
  - Two fragments 600 ms apart produce **one** AI reply that answers the merged text.
  - A complete sentence produces a reply without the extra wait.
- Run `uv run --project backend pytest -q tests`. It must stay green; it was 195 passed at `866faff`.

## Don't touch
`backend/caller/personas.py` (separate task: `docs/tasks/scammer_realism.md`) and the frontend.
