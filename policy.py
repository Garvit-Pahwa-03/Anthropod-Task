"""Deterministic combination of LLM evidence into the four output labels (assignment-v2).
Precedence D6: Invalid Lead > Not Interested > Appointment Scheduled > Follow-up Required > Unable to Assess.
Lead quality order: Not Qualified, Not Assessable, Low, High, Medium."""
from datetime import datetime
from typing import List, Optional, Tuple
from constants import VALID_PAIRS, FOLLOWUP_TIEBREAK, INVALID_TIEBREAK
from schemas import JourneyExtraction
from temporal import CallbackEvent, decide_next_call, consultation_offset_days, fmt, _fallback, parse_call_start

BLOCKER_ORDER = [b for b in FOLLOWUP_TIEBREAK if b in
                 ("Family Discussion", "Cost Concern", "Travel Constraint", "Current Treatment", "Treatment Concern")]

def _invalid_sub(j: JourneyExtraction) -> Optional[str]:
    flags = {"Test Enquiry": j.test_enquiry, "Wrong Contact": j.wrong_contact, "No Pain Need": j.no_pain_need,
             "Policy Exclusion": j.patient_under_15_known, "Outside Service Area": j.outside_service_area_permanent}
    for sub in INVALID_TIEBREAK:
        if flags[sub]: return sub
    return None

def classify(j: Optional[JourneyExtraction], events: Optional[List[CallbackEvent]], call_dt: datetime,
             notes: Optional[List[str]] = None) -> Tuple[dict, dict]:
    """Returns (prediction with exactly 4 labels, debug info)."""
    notes = list(notes or [])
    events = events or []

    if j is None:                                        # extraction failed -> documented conservative default
        nxt, tr = decide_next_call("Follow-up Required", call_dt, events)
        notes.append("journey extraction failed: default Follow-up/Further Discussion/Medium")
        return ({"disposition": "Follow-up Required", "sub_disposition": "Further Discussion",
                 "lead_quality": "Medium", "next_call_at": nxt}, {"trace": tr, "notes": notes, "path": "default"})

    # ---- disposition + sub_disposition (D6 precedence) ------------------------------------------
    inv = _invalid_sub(j)
    commit_ok = (j.consultation_commitment == "confirmed_slot" and j.consultation_has_clock_time_or_window)
    if inv:
        disp, sub = "Invalid Lead", inv
    elif j.final_stance != "none":
        disp, sub = "Not Interested", ("Do Not Contact" if j.final_stance == "do_not_contact" else "Explicit Refusal")
    elif commit_ok:
        disp = "Appointment Scheduled"
        sub = ("Rescheduled" if j.consultation_replaces_existing_or_missed
               else "Online Consultation" if j.consultation_modality == "online" else "Clinic Visit")
    elif not j.meaningful_pain_discussion:
        disp, sub = "Unable to Assess", "Incomplete Conversation"
    else:
        disp = "Follow-up Required"; sub = None           # decided below once next_call is known

    # ---- next_call_at (also tells us whether a specific callback / vague deferral exists) ----------
    next_call, trace = decide_next_call(disp, call_dt, events)
    rule = trace.get("rule") or ""

    if disp == "Follow-up Required":
        blockers = [b for b in BLOCKER_ORDER if b in j.open_blockers]
        if blockers:                       sub = blockers[0]
        elif rule.startswith("F3"):        sub = "Specific Callback"
        elif j.final_next_step_is_review_of_information: sub = "Information Requested"
        elif rule.startswith("F7"):        sub = "Vague Deferral"
        else:                              sub = "Further Discussion"

    # ---- lead quality -------------------------------------------------------------------------------
    offset = consultation_offset_days(call_dt, j.consultation_day) if j.consultation_commitment != "tentative_or_none" else None
    if disp == "Invalid Lead":
        lq = "Not Qualified"
    elif disp == "Unable to Assess" or j.need_or_willingness_unreliable:
        lq = "Not Assessable"
    elif (disp == "Not Interested" or j.exploratory_curiosity_only
          or (j.defers_more_than_30_days and disp != "Appointment Scheduled")):
        lq = "Low"
    elif (j.need_established and not j.open_blockers and j.consultation_commitment != "tentative_or_none"
          and (offset is None and disp == "Appointment Scheduled" or (offset is not None and 0 <= offset <= 6))):
        lq = "High"
    else:
        lq = "Medium"
    if disp == "Appointment Scheduled" and offset is None:
        notes.append("appointment date unresolvable -> offset unknown, treated as within 0-6")

    assert sub in VALID_PAIRS[disp], (disp, sub)
    return ({"disposition": disp, "sub_disposition": sub, "lead_quality": lq, "next_call_at": next_call},
            {"trace": trace, "notes": notes, "path": "policy", "consultation_offset": offset})
