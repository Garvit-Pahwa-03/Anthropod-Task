"""Per-record workflow: preprocess -> LLM call A (journey) + LLM call B (events) -> deterministic policy."""
from typing import Optional
from schemas import JourneyExtraction, EventsExtraction
from prompts import SYSTEM_JOURNEY, SYSTEM_EVENTS, USER_TEMPLATE
from policy import classify
from temporal import parse_call_start

def numbered(transcript: str):
    lines = [l.strip() for l in transcript.replace("\r\n", "\n").split("\n") if l.strip()]
    return "\n".join(f"[{i}] {l}" for i, l in enumerate(lines, 1)), len(lines)

def _bad_lines(obj_lines, n):
    return [x for x in obj_lines if not (1 <= x <= n)]

def process_record(rec: dict, extractor, prompts=None) -> tuple:
    """Returns (prediction dict with exactly 5 keys, debug dict). Never raises for model problems."""
    sys_journey, sys_events = (prompts or (SYSTEM_JOURNEY, SYSTEM_EVENTS))[:2]
    tid = rec.get("transcript_id")
    notes = []
    try:
        call_dt = parse_call_start(rec["call_started_at"])
        text, n_lines = numbered(rec["transcript"])
    except Exception as e:                                   # malformed input: still emit a valid record
        pred = {"transcript_id": tid, "disposition": "Unable to Assess", "sub_disposition": "Incomplete Conversation",
                "lead_quality": "Not Assessable", "next_call_at": None}
        return pred, {"transcript_id": tid, "notes": [f"bad input: {e}"], "path": "input_error"}

    user = USER_TEMPLATE.format(call_started_at=rec["call_started_at"], weekday=call_dt.strftime("%A"),
                                numbered_transcript=text)
    journey, mA = extractor.extract(sys_journey, user, JourneyExtraction, "journey")
    events_obj, mB = extractor.extract(sys_events, user, EventsExtraction, "events")
    if journey is None: notes.append("journey call failed")
    if events_obj is None: notes.append("events call failed -> no callback info")
    events = events_obj.events if events_obj else []

    if journey is not None:                                  # evidence sanity check (logged, not fatal)
        bad = _bad_lines(journey.final_stance_lines + journey.consultation_lines + journey.blocker_lines, n_lines)
        if bad: notes.append(f"journey cites non-existent lines {bad}")
    for e in events:
        bad = _bad_lines(e.evidence_lines, n_lines)
        if bad: notes.append(f"event {e.order} cites non-existent lines {bad}")

    labels, dbg = classify(journey, events, call_dt, notes)
    pred = {"transcript_id": tid, **labels}
    debug = {"transcript_id": tid, "journey": journey.model_dump() if journey else None,
             "events": [e.model_dump() for e in events], **dbg, "meta": {"journey": mA, "events": mB}}
    return pred, debug
