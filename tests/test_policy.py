import sys, pathlib, itertools, json
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import pytest, jsonschema
from schemas import JourneyExtraction, EventsExtraction, strict_schema
from policy import classify
from pipeline import process_record, numbered
from temporal import DaySpec as D, TimeSpec as T, TimeCandidate as C, CallbackEvent as E, parse_call_start
from constants import VALID_PAIRS

CALL = parse_call_start("2026-11-09T14:00:00+05:30")          # Monday

def J(**kw):
    base = dict(rationale="", clinic_agent_label="Agent", intended_patient="self", meaningful_pain_discussion=True,
                wrong_contact=False, no_pain_need=False, test_enquiry=False, patient_under_15_known=False,
                outside_service_area_permanent=False, final_stance="none", final_stance_lines=[],
                consultation_commitment="tentative_or_none", consultation_modality="clinic",
                consultation_replaces_existing_or_missed=False, consultation_has_clock_time_or_window=False,
                consultation_day=D(), consultation_lines=[], open_blockers=[], blocker_lines=[],
                final_next_step_is_review_of_information=False, need_established=True,
                exploratory_curiosity_only=False, need_or_willingness_unreliable=False, defers_more_than_30_days=False)
    base.update(kw); return JourneyExtraction(**base)

def booked(day=D(kind="tomorrow"), **kw):
    return J(consultation_commitment="confirmed_slot", consultation_has_clock_time_or_window=True, consultation_day=day, **kw)
def cbk(day, time=T(), order=1):
    return E(order=order, event_type="callback", acknowledged="yes", status="agreed", candidates=[C(day=day, time=time)])
VAGUE = E(order=1, event_type="vague_postponement", status="agreed", candidates=[C()])
def run(j, ev=()): return classify(j, list(ev), CALL)[0]

# ---- disposition / sub_disposition ---------------------------------------------------------------
def test_clinic_appointment_high():
    assert run(booked()) == {"disposition": "Appointment Scheduled", "sub_disposition": "Clinic Visit",
                             "lead_quality": "High", "next_call_at": None}
def test_online_appointment():    assert run(booked(consultation_modality="online"))["sub_disposition"] == "Online Consultation"
def test_rescheduled_beats_modality():
    assert run(booked(consultation_modality="online", consultation_replaces_existing_or_missed=True))["sub_disposition"] == "Rescheduled"
def test_confirmed_day_without_time_is_not_a_booking():
    j = J(consultation_commitment="confirmed_slot", consultation_has_clock_time_or_window=False, consultation_day=D(kind="tomorrow"))
    p = run(j); assert p["disposition"] == "Follow-up Required" and p["lead_quality"] == "High"   # commits within 7 days, no blocker
def test_explicit_refusal_low():
    p = run(J(final_stance="explicit_refusal")); assert (p["disposition"], p["sub_disposition"], p["lead_quality"], p["next_call_at"]) == ("Not Interested", "Explicit Refusal", "Low", None)
def test_do_not_contact_even_with_callback():
    p = run(J(final_stance="do_not_contact"), [cbk(D(kind="tomorrow"))]); assert p["sub_disposition"] == "Do Not Contact" and p["next_call_at"] is None
def test_invalid_beats_refusal_and_appointment():
    p = run(booked(wrong_contact=True, final_stance="explicit_refusal")); assert p["disposition"] == "Invalid Lead" and p["lead_quality"] == "Not Qualified"
def test_refusal_beats_appointment():  assert run(booked(final_stance="explicit_refusal"))["disposition"] == "Not Interested"
def test_invalid_tiebreak_order():
    assert run(J(wrong_contact=True, test_enquiry=True, no_pain_need=True))["sub_disposition"] == "Test Enquiry"
    assert run(J(no_pain_need=True, patient_under_15_known=True))["sub_disposition"] == "No Pain Need"
    assert run(J(patient_under_15_known=True, outside_service_area_permanent=True))["sub_disposition"] == "Policy Exclusion"
def test_unable_to_assess():
    p = run(J(meaningful_pain_discussion=False, need_established=False)); assert (p["disposition"], p["sub_disposition"], p["lead_quality"], p["next_call_at"]) == ("Unable to Assess", "Incomplete Conversation", "Not Assessable", None)

# ---- follow-up sub_disposition ----------------------------------------------------------------------
def test_blocker_tiebreak_order():
    assert run(J(open_blockers=["Treatment Concern", "Cost Concern"]))["sub_disposition"] == "Cost Concern"
    assert run(J(open_blockers=["Travel Constraint", "Family Discussion"]))["sub_disposition"] == "Family Discussion"
    assert run(J(open_blockers=["Treatment Concern", "Current Treatment"]))["sub_disposition"] == "Current Treatment"
def test_blocker_owns_sub_but_callback_still_extracted():
    p = run(J(open_blockers=["Family Discussion"]), [cbk(D(kind="tomorrow"), T(kind="period", period="afternoon"))])
    assert p["sub_disposition"] == "Family Discussion" and p["next_call_at"] == "2026-11-10T15:00:00+05:30"
def test_specific_callback():
    p = run(J(), [cbk(D(kind="weekday", weekday="fri"))]); assert p["sub_disposition"] == "Specific Callback" and p["next_call_at"] == "2026-11-13T11:00:00+05:30"
def test_information_requested():  assert run(J(final_next_step_is_review_of_information=True))["sub_disposition"] == "Information Requested"
def test_specific_callback_beats_information_requested():
    assert run(J(final_next_step_is_review_of_information=True), [cbk(D(kind="tomorrow"))])["sub_disposition"] == "Specific Callback"
def test_vague_deferral_plus3():
    p = run(J(), [VAGUE]); assert p["sub_disposition"] == "Vague Deferral" and p["next_call_at"] == "2026-11-12T11:00:00+05:30"
def test_further_discussion_plus1():
    p = run(J()); assert p["sub_disposition"] == "Further Discussion" and p["next_call_at"] == "2026-11-10T11:00:00+05:30"
def test_blocker_with_vague_postponement_uses_plus3():
    p = run(J(open_blockers=["Cost Concern"]), [VAGUE]); assert p["sub_disposition"] == "Cost Concern" and p["next_call_at"] == "2026-11-12T11:00:00+05:30"

# ---- lead quality -----------------------------------------------------------------------------------
def test_appointment_day_7_is_medium():   assert run(booked(day=D(kind="in_n_days", n=7)))["lead_quality"] == "Medium"
def test_appointment_day_6_is_high():     assert run(booked(day=D(kind="in_n_days", n=6)))["lead_quality"] == "High"
def test_defers_over_30_days_low():       assert run(J(defers_more_than_30_days=True))["lead_quality"] == "Low"
def test_confirmed_far_appointment_not_low():
    assert run(booked(day=D(kind="in_n_months", n=2), defers_more_than_30_days=True))["lead_quality"] == "Medium"
def test_curiosity_low():                 assert run(J(exploratory_curiosity_only=True))["lead_quality"] == "Low"
def test_unreliable_need_not_assessable(): assert run(J(need_or_willingness_unreliable=True))["lead_quality"] == "Not Assessable"
def test_default_medium():                assert run(J(open_blockers=["Cost Concern"]))["lead_quality"] == "Medium"
def test_blocker_prevents_high():
    assert run(J(consultation_commitment="day_commitment_only", consultation_day=D(kind="tomorrow"), open_blockers=["Travel Constraint"]))["lead_quality"] == "Medium"
def test_no_need_established_prevents_high():  assert run(booked(need_established=False))["lead_quality"] == "Medium"
def test_appointment_with_distinct_callback():
    p = run(booked(), [cbk(D(kind="tomorrow"), T(kind="period", period="morning"))]); assert p["next_call_at"] == "2026-11-10T10:00:00+05:30"

# ---- failure handling & fuzz ------------------------------------------------------------------------------
def test_failed_extraction_default_is_valid():
    p, d = classify(None, [], CALL); assert p["disposition"] == "Follow-up Required" and p["sub_disposition"] in VALID_PAIRS["Follow-up Required"]
def test_fuzz_always_valid_pair_and_values():
    flags = ["wrong_contact", "test_enquiry", "patient_under_15_known", "outside_service_area_permanent",
             "exploratory_curiosity_only", "need_or_willingness_unreliable", "defers_more_than_30_days",
             "final_next_step_is_review_of_information", "consultation_replaces_existing_or_missed", "need_established"]
    n = 0
    for bits in itertools.product([False, True], repeat=len(flags)):
        for stance in ("none", "explicit_refusal", "do_not_contact"):
            for commit in ("confirmed_slot", "day_commitment_only", "tentative_or_none"):
                for blockers in ([], ["Cost Concern", "Family Discussion"]):
                    if n % 7: n += 1; continue                    # thin the product to keep runtime small
                    n += 1
                    j = J(**dict(zip(flags, bits)), final_stance=stance, consultation_commitment=commit,
                          consultation_has_clock_time_or_window=bool(n % 2), consultation_day=D(kind="tomorrow"), open_blockers=blockers,
                          meaningful_pain_discussion=bool(n % 3))
                    for ev in ([], [VAGUE], [cbk(D(kind="tomorrow"))]):
                        p = run(j, ev)
                        assert p["sub_disposition"] in VALID_PAIRS[p["disposition"]]
                        assert p["lead_quality"] in ["Not Qualified", "Not Assessable", "Low", "Medium", "High"]
                        if p["disposition"] in ("Invalid Lead", "Not Interested", "Unable to Assess"): assert p["next_call_at"] is None
                        if p["disposition"] == "Appointment Scheduled" and not ev or ev == [VAGUE]: pass
                        if p["next_call_at"]: assert p["next_call_at"].endswith("+05:30") and len(p["next_call_at"]) == 25

# ---- schema ---------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("cls", [JourneyExtraction, EventsExtraction])
def test_strict_schema_is_strict_and_validates_instances(cls):
    s = strict_schema(cls)
    def check(node):
        if isinstance(node, dict):
            if "$ref" in node: raise AssertionError("unresolved $ref")
            if "properties" in node:
                assert node["additionalProperties"] is False and set(node["required"]) == set(node["properties"])
            for v in node.values(): check(v)
        elif isinstance(node, list):
            for v in node: check(v)
    check(s)
    inst = (J().model_dump() if cls is JourneyExtraction else
            {"events": [cbk(D(kind="tomorrow"), T(kind="clock", hour=4)).model_dump()]})
    jsonschema.validate(inst, s)

# ---- end-to-end with a stub model (no network) ---------------------------------------------------------------------
class StubExtractor:
    settings = {}
    def extract(self, system, user, model_cls, name):
        if name == "journey": return booked(day=D(kind="tomorrow")), {"prompt_tokens": 1, "completion_tokens": 1}
        return EventsExtraction(events=[]), {"prompt_tokens": 1, "completion_tokens": 1}

def test_end_to_end_stub_returns_exactly_five_keys():
    rec = {"transcript_id": "X-1", "call_started_at": "2026-11-09T14:00:00+05:30", "timezone": "Asia/Kolkata",
           "transcript": "Agent: Hello\n\nCustomer: Hi\nAgent: Tomorrow at 4?\nCustomer: Okay"}
    pred, dbg = process_record(rec, StubExtractor())
    assert set(pred) == {"transcript_id", "disposition", "sub_disposition", "lead_quality", "next_call_at"}
    assert pred["disposition"] == "Appointment Scheduled" and pred["next_call_at"] is None
    json.dumps(pred)

def test_numbering_skips_blank_lines():
    t, n = numbered("A: x\n\nB: y\r\nC: z"); assert n == 3 and t.splitlines()[1].startswith("[2] B")

def test_malformed_record_still_emits_valid_prediction():
    pred, _ = process_record({"transcript_id": "X-2", "call_started_at": "garbage", "transcript": "x"}, StubExtractor())
    assert pred["transcript_id"] == "X-2" and pred["next_call_at"] is None

# ---- switchable prompt changes -------------------------------------------------------------------------------
def test_prompt_switches_are_independent_and_baseline_is_v1():
    import prompts
    j0, e0, v0 = prompts.build_prompts(())
    assert v0 == "v1-baseline" and "STILL OPEN at the end" in j0 and "<<" not in j0 + e0
    jb, eb, vb = prompts.build_prompts(("blockers",))
    assert "MAIN stated obstacle" in jb and eb == e0 and vb == "v1+blockers"
    jv, ev, _ = prompts.build_prompts(("vague",))
    assert jv == j0 and ev != e0
    with pytest.raises(ValueError): prompts.build_prompts(("nonsense",))

def test_pipeline_uses_supplied_prompts():
    seen = []
    class Spy(StubExtractor):
        def extract(self, system, user, model_cls, name): seen.append((name, system)); return super().extract(system, user, model_cls, name)
    rec = {"transcript_id": "X-3", "call_started_at": "2026-11-09T14:00:00+05:30", "transcript": "Agent: hi\nCustomer: hello"}
    process_record(rec, Spy(), ("JOURNEY-PROMPT", "EVENTS-PROMPT"))
    assert seen == [("journey", "JOURNEY-PROMPT"), ("events", "EVENTS-PROMPT")]
