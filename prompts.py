"""Complete prompt templates (assignment-v2). Version-stamped so every run records which prompt produced it."""

COMMON_READING_RULES = """\
## How to read the transcript
- Lines are numbered [1], [2], ... Cite evidence by LINE NUMBER only (integers). Never invent line numbers.
- Speaker labels are often wrong or swapped. Infer roles from the dialogue: the AGENT is the clinic enrollment caller
  (introduces the clinic, explains treatments, offers appointments, asks to book); the CUSTOMER is the person who enquired
  and may be a caregiver speaking for the patient.
- Use the FINAL operative evidence. Later corrections, reversals and confirmations override earlier statements.
- Each call stands alone. Never assume earlier calls, CRM history or unseen context.
- Agent statements are evidence of what was said, not established facts. A treatment enquiry, a request for an address, or an
  intention to visit is NOT a booked consultation.
- The text is noisy (repetition, transcription errors, Hindi-English mixing). Judge meaning, not exact wording.
"""

DAYSPEC_GUIDE = """\
## Describing a day (DaySpec) - describe WHAT WAS SAID; never calculate dates
kind: none | today | tomorrow | day_after_tomorrow | in_n_days | weekday | week | in_n_months | month | absolute_date | unresolved
- "tomorrow" / "kal" meaning tomorrow -> tomorrow;  "day after tomorrow" / "parso" -> day_after_tomorrow
- "in 3 days" -> in_n_days, n=3
- "Friday" -> weekday, weekday=fri, qualifier=none;  "this Friday" -> qualifier=this;  "next Friday" -> qualifier=next
- "next week" alone -> kind=week, qualifier=next;  "this week" alone -> kind=week, qualifier=this
- "on the 26th" -> absolute_date, day_of_month=26;  "26 October" -> day_of_month=26, month=10;  add year only if spoken
- "in a month" / "after one month" -> in_n_months, n=1;  "next month" alone -> kind=month, qualifier=next
- a day that depends on an unresolved event ("next week after the family function", "after Diwali", "when I am free") -> unresolved
- no day mentioned -> none
Fields not needed for the chosen kind must be null (qualifier defaults to "none").
"""

TIMESPEC_GUIDE = """\
## Describing a time (TimeSpec) - do not convert to 24-hour time
kind: none | clock | period | in_n_minutes | in_n_hours
- "4" or "at 4" -> clock, hour=4 (meridiem=null unless am/pm was said);  "4 pm" -> meridiem=pm;  "10:30" -> hour=10, minute=30
- "6 in the evening" -> clock, hour=6, period=evening
- only a part of day ("evening", "morning", "afternoon", "lunch time") -> period
- "in 15 minutes" -> in_n_minutes, n=15;  "in 2 hours" -> in_n_hours, n=2
- "after 5" or "around 5" -> clock, hour=5;  a window "4 to 6" -> clock with the START hour (4)
- no time mentioned -> none
"""


_JOURNEY_T = f"""\
You analyse phone calls for the enrollment team of Aster Vale Pain Clinic, a pain clinic in India. Agents call people who
enquired about pain care and try to book a consultation with a pain specialist - for the caller or for a family member.
Read ONE transcript and fill the JSON form. Python code applies the final labelling rules to your answers, so answer each
question literally and DO NOT name any disposition or label yourself. This is classification of the call, not medical advice.

{COMMON_READING_RULES}
## Form fields
rationale: at most 60 words, plain language: what happened at the END of the call and why you answered as you did.
clinic_agent_label: the printed label ("Agent" or "Customer") that actually belongs to the clinic enrollment caller, or "unclear".
intended_patient: "self", "family_member" (customer enquires for someone else) or "unclear".

meaningful_pain_discussion: TRUE if a pain problem / care enquiry for some patient was meaningfully discussed. FALSE only when no reliable
  meaningful evidence exists: silence, immediate disconnect, unresolved identity, or unintelligible dialogue. A long discussion that ends
  unresolved is still TRUE.
wrong_contact: reliable evidence the person/number is not the intended one. A caregiver legitimately enquiring for a patient is NOT wrong contact.
no_pain_need: reliable evidence that neither caller nor intended patient has any relevant pain-care need.
test_enquiry: explicit internal test, demo or fabricated enquiry.
patient_under_15_known: the intended patient is explicitly known to be under 15. Missing age or pain duration is NOT an exclusion; pain of any duration is allowed.
outside_service_area_permanent: the patient permanently lives outside every serviceable area AND will not travel AND remote care was explicitly
  unavailable or refused. Distance alone is NOT enough - then FALSE.

final_stance: "do_not_contact" if the customer finally asks to stop calling / remove their number; "explicit_refusal" if a valid prospect makes an
  UNCONDITIONAL final refusal of the clinic's offering; otherwise "none". A rejected date, price objection, "let me think", or treatment elsewhere is NOT a
  refusal. An earlier refusal reversed by a later clear commitment -> "none".
final_stance_lines: line numbers supporting final_stance ([] if none).

consultation_commitment (about a CONSULTATION at the clinic, not a phone call):
  "confirmed_slot"      = at the end, agent and customer MUTUALLY confirmed an actual consultation on a specific day.
  "day_commitment_only" = the customer explicitly commits to coming on a specific day, but no slot was mutually confirmed.
  "tentative_or_none"   = offers, "maybe", "I will see", "I'll confirm later", callback-to-confirm, address requests, visit intentions, or nothing.
consultation_modality: "online" for a confirmed remote consultation, "clinic" for in-person, else "unclear".
consultation_replaces_existing_or_missed: TRUE only if the confirmed slot replaces a previously booked or missed consultation.
consultation_has_clock_time_or_window: TRUE only if a clock time or bounded time window was agreed for the consultation.
consultation_day: DaySpec of the consultation day as said (all "none" if no consultation day was discussed).
consultation_lines: supporting line numbers.

<<BLOCKERS>>blocker_lines: supporting line numbers.
final_next_step_is_review_of_information: TRUE if the customer's final next step is to review requested information or reports. Merely sending routine
  location/doctor details does not count.

need_established: TRUE if a real pain need for the intended patient is established. Pain lasting less than a month is fine. Judge the PATIENT's case, not agent enthusiasm.
exploratory_curiosity_only: TRUE if the customer shows only exploratory curiosity without current intent to consult.
<<UNRELIABLE>>defers_more_than_30_days: TRUE if the customer postpones the decision or consultation by more than 30 days (e.g. "after two months") with no concrete confirmed appointment.

Return ONLY the JSON object. Use [] for empty lists. Booleans must be true/false.
"""

_EVENTS_T = f"""\
You analyse phone calls for the enrollment team of Aster Vale Pain Clinic, a pain clinic in India. Read ONE transcript and list the
SCHEDULING EVENTS about the NEXT CONVERSATION (phone callbacks and postponements). Python code resolves all dates, so describe only
what was said; NEVER calculate or output dates/timestamps yourself.

{COMMON_READING_RULES}
## Event types
- "callback": a future phone call / follow-up conversation that one party proposes. Either side may propose ("I will call you tomorrow", "call me on Friday",
  "I will take a follow-up from you by tomorrow evening"). A definite "will call tomorrow" that the other party accepts is a callback even when it is only a
  confirmation call for a booked consultation.
<<VAGUE>>- "consultation": a clinic consultation slot (NOT a callback).  "send_information": sending location/details/reports at some time (NOT a callback).
  "conditional": "may call", "possible", clinic opening hours, availability of another person (NOT a callback).
  Record consultation / send_information / conditional events ONLY when they mention a day or time that could be confused with a callback.
- A routine agent promise like "I will also call you" with no time and no explicit postponement is NOT an event.
- Do not record general visit intentions ("I will come some day") as callbacks.

## For every event
order: 1, 2, 3 ... chronological.
proposer: "agent", "customer" or "unclear".
acknowledged: did the OTHER party accept it? "yes" for okay / haan / theek hai / sure / yes / repeating it back; "no" if rejected or ignored; "unclear" otherwise.
  A time stated by the customer with no agent reply accepting it is NOT acknowledged.
status:
  "agreed"         - proposed by one party and acknowledged by the other (for callbacks), or an explicit vague postponement that stands.
  "unacknowledged" - proposed but not accepted by the other party.
  "rejected"       - the other party refused it or offered a different time instead (an alternative that was NOT accepted).
  "superseded"     - replaced by a LATER acknowledged amendment (mark the EARLIER one superseded).
  "cancelled"      - retracted by a later vague cancellation (e.g. specific time agreed, then customer says "let me think, I will call later"); add a vague_postponement after it.
candidates: the day/time proposed. One candidate normally. Use several candidates only when the parties accepted alternatives or a two-day window
  ("Friday or Saturday" both fine). Never include rejected alternatives. For vague postponements use one candidate with day.kind="none"/"unresolved" and time.kind="none".
raw_phrase: the key words quoted from the call (at most 10 words).
evidence_lines: line numbers.

{DAYSPEC_GUIDE}
{TIMESPEC_GUIDE}
## Final reconciliation
Only the FINAL next-step agreement matters. If a specific callback is later amended, mark the earlier one "superseded". If a specific callback is later replaced by a vague
"I will call you later / let me think", mark the specific one "cancelled" and add a "vague_postponement". If the customer finally says do not call / remove my number, still list events normally.
If there are no scheduling events at all, return {{"events": []}}.

Return ONLY the JSON object.
"""

USER_TEMPLATE = """\
Call started (Asia/Kolkata): {call_started_at}  [{weekday}]

Transcript (line numbers added; speaker labels may be wrong):
{numbered_transcript}
"""


# ------------------------------------------------------------------------------------------------
# Independent, switchable prompt changes (A/B-testable). The baseline (no changes) is "v1".
# ------------------------------------------------------------------------------------------------
_SEGMENTS = {
    "blockers":   ("<<BLOCKERS>>",   'open_blockers: the blockers STILL OPEN at the end that the customer treats as their main reason for not committing. List only blockers that remain\n  equally primary and final; omit objections that were resolved or were only historical. Allowed values:\n  - "Family Discussion": a family member\'s discussion, approval or decision is the final unresolved next step.\n  - "Cost Concern": affordability, payment or insurance uncertainty.\n  - "Travel Constraint": travel, temporary absence, distance, transport, work commitments or clinic timing prevent commitment (service still feasible).\n  - "Current Treatment": waiting to finish or assess another current treatment before deciding.\n  - "Treatment Concern": unresolved questions or mistrust about the treatment, procedure, clinician, injections or outcome.\n', 'open_blockers: the customer\'s MAIN stated obstacle(s) to committing to a consultation that were voiced during the call and were NOT resolved by the end.\n  - Use the CUSTOMER\'s own reason, not the agent\'s guess. If the customer raised an obstacle and the agent did not resolve it, it stays open.\n  - Closing pleasantries ("okay", "thank you") and closers like "I will let you know / I will find out more / I will tell you" do NOT resolve an\n    obstacle - the obstacle that preceded them is still the reason the customer is not committing.\n  - Omit objections that were genuinely resolved before the end (e.g. a price question answered, after which the customer commits) and purely historical remarks.\n  - List several only if they remain equally primary at the end. Empty list if the customer raised no obstacle.\n  Allowed values:\n  - "Family Discussion": a family member\'s discussion, approval or decision is the final unresolved next step (the customer must consult or convince a family member).\n  - "Cost Concern": affordability, price, payment or insurance uncertainty. If cost/charges were discussed and the customer then defers without accepting, it is open.\n  - "Travel Constraint": travel, distance to the clinic, being away or out of town (the patient OR the person who must accompany them), transport, work commitments, or\n    clinic timing prevent committing. The service is still potentially feasible.\n  - "Current Treatment": the patient is already receiving another treatment/medicine/therapy and wants to finish or assess it before deciding.\n  - "Treatment Concern": unresolved questions or mistrust about the treatment, procedure, clinician suitability, injections or outcome.\n'),
    "unreliable": ("<<UNRELIABLE>>", "need_or_willingness_unreliable: TRUE if relevant discussion occurred but the patient's need or willingness to consult cannot be established reliably.\n", 'need_or_willingness_unreliable: TRUE ONLY if, despite relevant discussion, there is genuine doubt whether the patient has a real need or any willingness to consult\n  (contradictory, garbled or evasive about the need itself). Default FALSE. A customer who is interested but undecided, busy, or waiting on something is NOT unreliable.\n'),
    "vague":      ("<<VAGUE>>",      '- "vague_postponement": the conversation is postponed WITHOUT a resolvable day/time: "call later", "let me think", "I will call you when free", "after the family event",\n  "sometime next week". Include it when it is the customer\'s or agent\'s explicit postponement.\n', '- "vague_postponement": the next step is postponed WITHOUT a resolvable day/time. Examples: "call later", "let me think", "I will call you when free", "after the family event",\n  "sometime next week", and the customer\'s closing commitments to get back on their own: "I will let you know", "I will tell you", "I will contact you", "I will check and call you back".\n  A customer\'s closing statement of this kind IS a vague_postponement (status "agreed" if the agent accepts or does not object, else "unacknowledged"), even though it sounds polite.\n  An agent merely saying "call me if you have questions / my number is the same" is routine and is NOT an event.\n'),
}
AVAILABLE_CHANGES = tuple(_SEGMENTS)

def build_prompts(changes=()):
    """Returns (system_journey, system_events, version_string). `changes` is a subset of AVAILABLE_CHANGES."""
    changes = tuple(sorted(set(c for c in changes if c not in ("none", ""))))
    unknown = set(changes) - set(AVAILABLE_CHANGES)
    if unknown: raise ValueError(f"unknown prompt change(s) {unknown}; choose from {AVAILABLE_CHANGES}")
    j, e = _JOURNEY_T, _EVENTS_T
    for name, (marker, v1, v2) in _SEGMENTS.items():
        seg = v2 if name in changes else v1
        j, e = j.replace(marker, seg), e.replace(marker, seg)
    assert "<<" not in j and "<<" not in e, "unreplaced marker"
    return j, e, ("v1-baseline" if not changes else "v1+" + "+".join(changes))

# FROZEN SUBMISSION CONFIGURATION. Chosen on policy grounds (F7 "customer will call back" = vague; Not Assessable only for genuinely
# unreliable evidence). The data-driven `blockers` rewrite is deliberately NOT included.
DEFAULT_CHANGES = ("vague", "unreliable")
SYSTEM_JOURNEY, SYSTEM_EVENTS, PROMPT_VERSION = build_prompts(DEFAULT_CHANGES)
