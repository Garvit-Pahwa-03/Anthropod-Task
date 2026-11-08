"""Unit tests for temporal.py. Run:  python -m pytest -q tests/
Anchors: 2026-11-09 is a Monday (the policy's own boundary examples use it).
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import pytest
from temporal import (DaySpec as D, TimeSpec as T, TimeCandidate as C, CallbackEvent as E,
                      resolve_expression, resolve_candidates, decide_next_call, parse_call_start,
                      consultation_offset_days, fmt)

MON_1400 = parse_call_start("2026-11-09T14:00:00+05:30")          # Monday 14:00
def R(call, day, time=T()):
    r = resolve_expression(parse_call_start(call), day, time)
    return (fmt(r.dt) if r.dt else None), r.status

def cb(order, day, time=T(), status="agreed", ack="yes", raw=""):
    return E(order=order, event_type="callback", acknowledged=ack, status=status,
             candidates=[C(day=day, time=time)], raw_phrase=raw)
def vague(order, status="agreed"):
    return E(order=order, event_type="vague_postponement", status=status, raw_phrase="later")

# ---- policy boundary examples EX1-EX6 -------------------------------------------------------
def test_EX1_tomorrow_at_4():
    out, _ = decide_next_call("Follow-up Required", MON_1400,
                              [cb(1, D(kind="tomorrow"), T(kind="clock", hour=4))])
    assert out == "2026-11-10T16:00:00+05:30"

def test_EX2_vague_deferral_plus3():
    out, tr = decide_next_call("Follow-up Required", MON_1400, [vague(1)])
    assert out == "2026-11-12T11:00:00+05:30" and "F7" in tr["rule"]

def test_EX3_appointment_no_callback_is_null():
    assert decide_next_call("Appointment Scheduled", MON_1400, [])[0] is None

def test_EX4_unspecified_agent_call_plus1():
    out, tr = decide_next_call("Follow-up Required", MON_1400, [])
    assert out == "2026-11-10T11:00:00+05:30" and "F8" in tr["rule"]

def test_EX5_do_not_contact_suppresses():
    ev = [cb(1, D(kind="tomorrow"), T(kind="clock", hour=4))]
    assert decide_next_call("Not Interested", MON_1400, ev)[0] is None

# ---- F4 relative days / weekdays ---------------------------------------------------------------
@pytest.mark.parametrize("day,expected", [
    (D(kind="tomorrow"),                                   "2026-11-10T11:00:00+05:30"),
    (D(kind="day_after_tomorrow"),                         "2026-11-11T11:00:00+05:30"),
    (D(kind="in_n_days", n=5),                             "2026-11-14T11:00:00+05:30"),
    (D(kind="weekday", weekday="fri"),                     "2026-11-13T11:00:00+05:30"),
    (D(kind="weekday", weekday="mon"),                     "2026-11-16T11:00:00+05:30"),   # same weekday -> STRICTLY future
    (D(kind="weekday", weekday="mon", qualifier="this"),   "2026-11-16T11:00:00+05:30"),   # today's 11:00 already past
    (D(kind="weekday", weekday="wed", qualifier="next"),   "2026-11-18T11:00:00+05:30"),   # following Mon-Sun week
    (D(kind="weekday", weekday="sun", qualifier="next"),   "2026-11-22T11:00:00+05:30"),
    (D(kind="week", qualifier="next"),                     "2026-11-16T11:00:00+05:30"),   # next week alone -> next Monday
])
def test_relative_days(day, expected):
    assert R("2026-11-09T14:00:00+05:30", day) == (expected, "resolved")

def test_this_week_alone_is_vague():
    assert R("2026-11-09T14:00:00+05:30", D(kind="week", qualifier="this"))[1] == "vague"

def test_this_weekday_today_with_future_time():
    assert R("2026-11-09T09:00:00+05:30", D(kind="weekday", weekday="mon", qualifier="this"),
             T(kind="clock", hour=4))[0] == "2026-11-09T16:00:00+05:30"

def test_next_weekday_from_sunday_anchor():                # Sunday 2026-11-08: "next Monday" = following week's Monday
    assert R("2026-11-08T10:00:00+05:30", D(kind="weekday", weekday="mon", qualifier="next"))[0] == "2026-11-09T11:00:00+05:30"

# ---- F5 clock rules ----------------------------------------------------------------------------
@pytest.mark.parametrize("t,expected_hhmm", [
    (T(kind="clock", hour=4),                       "16:00"),   # 1-7 -> PM
    (T(kind="clock", hour=7, minute=30),            "19:30"),
    (T(kind="clock", hour=9),                       "09:00"),   # 8-11 -> AM
    (T(kind="clock", hour=11),                      "11:00"),
    (T(kind="clock", hour=12),                      "12:00"),   # 12 -> noon
    (T(kind="clock", hour=4, meridiem="am"),        "04:00"),   # explicit wins
    (T(kind="clock", hour=9, meridiem="pm"),        "21:00"),
    (T(kind="clock", hour=6, period="evening"),     "18:00"),
    (T(kind="clock", hour=9, period="morning"),     "09:00"),
    (T(kind="clock", hour=15, minute=45),           "15:45"),   # 24h
    (T(kind="period", period="morning"),            "10:00"),
    (T(kind="period", period="afternoon"),          "15:00"),
    (T(kind="period", period="evening"),            "18:00"),
    (T(kind="period", period="lunch"),              "13:00"),
])
def test_clock_rules(t, expected_hhmm):
    out, st = R("2026-11-09T14:00:00+05:30", D(kind="tomorrow"), t)
    assert st == "resolved" and out[11:16] == expected_hhmm

def test_time_only_today_if_future_else_tomorrow():
    assert R("2026-11-09T14:00:00+05:30", D(), T(kind="clock", hour=5))[0] == "2026-11-09T17:00:00+05:30"   # 5 -> 17:00 future
    assert R("2026-11-09T14:00:00+05:30", D(), T(kind="clock", hour=10))[0] == "2026-11-10T10:00:00+05:30"  # 10:00 past -> tomorrow

def test_bounded_window_uses_start_via_start_time():
    assert R("2026-11-09T14:00:00+05:30", D(kind="tomorrow"), T(kind="clock", hour=11))[0] == "2026-11-10T11:00:00+05:30"

# ---- F10 intervals -------------------------------------------------------------------------------
def test_in_15_minutes_preserves_seconds():                  # real example: AVT-047
    assert R("2026-10-15T14:11:01+05:30", D(), T(kind="in_n_minutes", n=15)) == ("2026-10-15T14:26:01+05:30", "resolved")
def test_in_2_hours_crosses_midnight():
    assert R("2026-12-31T23:10:30+05:30", D(), T(kind="in_n_hours", n=2))[0] == "2027-01-01T01:10:30+05:30"

def test_two_date_window_picks_earliest():
    cands = [C(day=D(kind="weekday", weekday="fri")), C(day=D(kind="weekday", weekday="wed"))]
    r = resolve_candidates(MON_1400, cands)
    assert fmt(r.dt) == "2026-11-11T11:00:00+05:30"

# ---- F6 absolute dates & past rejection ------------------------------------------------------------
def test_month_day_no_year_next_future_occurrence():
    assert R("2026-11-09T14:00:00+05:30", D(kind="absolute_date", month=11, day_of_month=5))[0] == "2027-11-05T11:00:00+05:30"
    assert R("2026-11-09T14:00:00+05:30", D(kind="absolute_date", month=11, day_of_month=20))[0] == "2026-11-20T11:00:00+05:30"

def test_explicit_past_full_date_rejected_not_repaired():
    assert R("2026-11-09T14:00:00+05:30", D(kind="absolute_date", year=2026, month=11, day_of_month=5)) == (None, "rejected")

def test_explicit_past_same_day_time_rejected():
    assert R("2026-11-09T14:00:00+05:30", D(kind="today"), T(kind="clock", hour=10)) == (None, "rejected")

def test_day_number_only():                                   # "after the 25th ... call on the 26th" (AVT-017)
    assert R("2026-10-15T18:28:03+05:30", D(kind="absolute_date", day_of_month=26))[0] == "2026-10-26T11:00:00+05:30"
    assert R("2026-10-27T10:00:00+05:30", D(kind="absolute_date", day_of_month=26))[0] == "2026-11-26T11:00:00+05:30"

def test_invalid_calendar_date_is_vague_not_crash():
    assert R("2026-11-09T14:00:00+05:30", D(kind="absolute_date", month=2, day_of_month=30))[1] == "vague"

# ---- F11 months ---------------------------------------------------------------------------------------
def test_in_one_month_clamps_to_month_end():
    assert R("2026-01-31T10:00:00+05:30", D(kind="in_n_months", n=1))[0] == "2026-02-28T11:00:00+05:30"
def test_in_one_month_leap_year():
    assert R("2028-01-31T10:00:00+05:30", D(kind="in_n_months", n=1))[0] == "2028-02-29T11:00:00+05:30"
def test_bare_next_month_first_day_11():
    assert R("2026-12-15T10:00:00+05:30", D(kind="month", qualifier="next"))[0] == "2027-01-01T11:00:00+05:30"

# ---- F12 conditional / event-only ------------------------------------------------------------------------
def test_event_only_reference_is_vague():
    assert R("2026-11-09T14:00:00+05:30", D(kind="unresolved"))[1] == "vague"

# ---- F3 / F7 / F9 selection logic --------------------------------------------------------------------------
def test_acknowledged_amendment_replaces_earlier():
    ev = [cb(1, D(kind="tomorrow"), status="superseded"), cb(2, D(kind="weekday", weekday="fri"))]
    assert decide_next_call("Follow-up Required", MON_1400, ev)[0] == "2026-11-13T11:00:00+05:30"

def test_final_vague_cancellation_discards_specific_time():
    ev = [cb(1, D(kind="tomorrow")), vague(2)]
    out, tr = decide_next_call("Follow-up Required", MON_1400, ev)
    assert out == "2026-11-12T11:00:00+05:30" and "F7" in tr["rule"]

def test_unacknowledged_customer_time_is_not_a_callback():
    ev = [cb(1, D(kind="tomorrow"), T(kind="clock", hour=4), status="unacknowledged", ack="no")]
    assert decide_next_call("Follow-up Required", MON_1400, ev)[0] == "2026-11-10T11:00:00+05:30"   # +1 fallback, NOT +3

def test_rejected_callback_does_not_imply_vague():
    ev = [cb(1, D(kind="tomorrow"), status="rejected", ack="no")]
    assert decide_next_call("Follow-up Required", MON_1400, ev)[0] == "2026-11-10T11:00:00+05:30"

def test_consultation_slot_and_send_info_are_not_callbacks():
    ev = [E(order=1, event_type="consultation", status="agreed", acknowledged="yes", candidates=[C(day=D(kind="tomorrow"))]),
          E(order=2, event_type="send_information", status="agreed", acknowledged="yes", candidates=[C(day=D(kind="tomorrow"))])]
    assert decide_next_call("Follow-up Required", MON_1400, ev)[0] == "2026-11-10T11:00:00+05:30"      # falls to +1

def test_appointment_with_distinct_callback_uses_it():
    ev = [cb(1, D(kind="tomorrow"), T(kind="period", period="morning"))]
    assert decide_next_call("Appointment Scheduled", MON_1400, ev)[0] == "2026-11-10T10:00:00+05:30"

def test_appointment_ignores_vague_and_never_gets_fallback():
    assert decide_next_call("Appointment Scheduled", MON_1400, [vague(1)])[0] is None

def test_callback_this_week_alone_falls_to_vague_plus3():
    ev = [cb(1, D(kind="week", qualifier="this"))]
    assert decide_next_call("Follow-up Required", MON_1400, ev)[0] == "2026-11-12T11:00:00+05:30"

def test_year_rollover_fallback():
    c = parse_call_start("2026-12-30T20:00:00+05:30")
    assert decide_next_call("Follow-up Required", c, [vague(1)])[0] == "2027-01-02T11:00:00+05:30"

@pytest.mark.parametrize("disp", ["Invalid Lead", "Not Interested", "Unable to Assess"])
def test_suppression_for_all_terminal_dispositions(disp):
    assert decide_next_call(disp, MON_1400, [cb(1, D(kind="tomorrow"))])[0] is None

# ---- lead-quality offset (High = 0-6, Medium = >=7) -----------------------------------------------------------
def test_consultation_offset_boundaries():
    assert consultation_offset_days(MON_1400, D(kind="today")) == 0
    assert consultation_offset_days(MON_1400, D(kind="in_n_days", n=6)) == 6      # High boundary
    assert consultation_offset_days(MON_1400, D(kind="in_n_days", n=7)) == 7      # Medium boundary
    assert consultation_offset_days(MON_1400, D(kind="weekday", weekday="mon")) == 7   # "Monday" said on a Monday = +7

# ---- golden fixtures from the labeled set (gold next_call_at verified) ----------------------------------------------
GOLD_CASES = [
    # id, call_started_at, disposition, events, gold
    ("AVT-004", "2026-10-14T13:19:21+05:30", "Follow-up Required",
     [cb(1, D(kind="tomorrow"), T(kind="period", period="evening"))], "2026-10-15T18:00:00+05:30"),
    ("AVT-011", "2026-10-13T14:35:21+05:30", "Follow-up Required",
     [cb(1, D(kind="tomorrow"), T(kind="period", period="afternoon"))], "2026-10-14T15:00:00+05:30"),
    ("AVT-014", "2026-10-14T15:13:56+05:30", "Follow-up Required",
     [cb(1, D(kind="weekday", weekday="fri"))], "2026-10-16T11:00:00+05:30"),
    ("AVT-017", "2026-10-15T18:28:03+05:30", "Follow-up Required",
     [cb(1, D(kind="absolute_date", day_of_month=26))], "2026-10-26T11:00:00+05:30"),
    ("AVT-023", "2026-10-14T10:38:33+05:30", "Follow-up Required",
     [cb(1, D(kind="absolute_date", day_of_month=22))], "2026-10-22T11:00:00+05:30"),
    ("AVT-047", "2026-10-15T14:11:01+05:30", "Follow-up Required",
     [cb(1, D(), T(kind="in_n_minutes", n=15))], "2026-10-15T14:26:01+05:30"),
    ("AVT-001", "2026-10-17T20:42:51+05:30", "Follow-up Required", [vague(1)], "2026-10-20T11:00:00+05:30"),
    ("AVT-015", "2026-10-15T19:12:47+05:30", "Follow-up Required", [], "2026-10-16T11:00:00+05:30"),
    ("AVT-002", "2026-10-14T19:57:16+05:30", "Appointment Scheduled", [], None),
    ("AVT-010", "2026-10-17T11:34:19+05:30", "Not Interested", [], None),
]
@pytest.mark.parametrize("tid,call,disp,events,gold", GOLD_CASES, ids=[c[0] for c in GOLD_CASES])
def test_golden_fixtures(tid, call, disp, events, gold):
    assert decide_next_call(disp, parse_call_start(call), events)[0] == gold
