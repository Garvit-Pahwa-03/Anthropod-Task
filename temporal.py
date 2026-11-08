"""Deterministic date/time resolver and next_call_at decision engine (rules F1-F12).

The LLM never writes timestamps. It only fills the closed schemas below (DaySpec / TimeSpec /
CallbackEvent) describing WHAT WAS SAID. Everything here is calendar arithmetic in fixed IST (+05:30),
anchored on call_started_at - never on the machine's clock.
"""
from __future__ import annotations
import calendar
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import List, Literal, Optional, Tuple
from pydantic import BaseModel, Field
from constants import (IST_OFFSET_MINUTES, DEFAULT_CALLBACK_HOUR,
                       VAGUE_FALLBACK_DAYS, OTHER_FALLBACK_DAYS)

IST = timezone(timedelta(minutes=IST_OFFSET_MINUTES))
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
PERIOD_DEFAULT_HOUR = {"morning": 10, "afternoon": 15, "evening": 18, "lunch": 13}   # F5

# ----------------------------------------------------------------------------------------------
# Closed vocabularies the LLM must use
# ----------------------------------------------------------------------------------------------
class DaySpec(BaseModel):
    kind: Literal["none", "today", "tomorrow", "day_after_tomorrow", "in_n_days", "weekday",
                  "week", "in_n_months", "month", "absolute_date", "unresolved"] = "none"
    n: Optional[int] = None                                     # in_n_days / in_n_months
    weekday: Optional[Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]] = None
    qualifier: Literal["none", "this", "next"] = "none"         # weekday / week / month
    day_of_month: Optional[int] = None                          # absolute_date ("on the 26th", "Oct 5")
    month: Optional[int] = None
    year: Optional[int] = None

class TimeSpec(BaseModel):
    kind: Literal["none", "clock", "period", "in_n_minutes", "in_n_hours"] = "none"
    hour: Optional[int] = None                                  # as spoken (1-12) or 24h (13-23)
    minute: Optional[int] = None
    meridiem: Optional[Literal["am", "pm"]] = None
    period: Optional[Literal["morning", "afternoon", "evening", "lunch", "night"]] = None
    n: Optional[int] = None                                     # in_n_minutes / in_n_hours

class TimeCandidate(BaseModel):
    day: DaySpec = Field(default_factory=DaySpec)
    time: TimeSpec = Field(default_factory=TimeSpec)

class CallbackEvent(BaseModel):
    order: int
    event_type: Literal["callback", "consultation", "send_information",
                        "vague_postponement", "conditional", "other"]
    proposer: Literal["agent", "customer", "unclear"] = "unclear"
    acknowledged: Literal["yes", "no", "unclear"] = "unclear"   # by the OTHER party
    status: Literal["agreed", "unacknowledged", "rejected", "superseded", "cancelled"] = "unacknowledged"
    candidates: List[TimeCandidate] = Field(default_factory=list)   # >1 only for accepted alternatives / windows
    raw_phrase: str = ""                                            # <=10 words quoted from the call
    evidence_lines: List[int] = Field(default_factory=list)         # transcript line numbers

# ----------------------------------------------------------------------------------------------
# Low-level helpers
# ----------------------------------------------------------------------------------------------
@dataclass
class Resolution:
    status: Literal["resolved", "vague", "rejected"]
    dt: Optional[datetime] = None
    reason: str = ""

def parse_call_start(s: str) -> datetime:
    """call_started_at -> aware datetime in IST (seconds preserved)."""
    return datetime.fromisoformat(s).astimezone(IST).replace(microsecond=0)

def fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + "+05:30"

def add_months(d: date, n: int) -> date:
    """Same day number n months later, clamped to the last day of that month (F11)."""
    m0 = d.month - 1 + n
    y, m = d.year + m0 // 12, m0 % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))

def to_24h(hour: int, meridiem: Optional[str], period: Optional[str]) -> int:
    if hour >= 13: return hour                                  # already 24h
    if meridiem == "am": return hour % 12
    if meridiem == "pm": return hour % 12 + 12
    if period == "morning": return hour % 12
    if period in ("afternoon", "evening", "night"): return hour % 12 + 12 if hour != 12 else 12
    if 1 <= hour <= 7: return hour + 12                         # F5: 1-7 -> PM
    return hour                                                  # 8-11 AM, 12 noon

def _time_of_day(t: TimeSpec) -> Optional[dtime]:
    """Clock part of a TimeSpec, or None when no clock info (-> default 11:00 applied by caller)."""
    if t.kind == "clock" and t.hour is not None:
        h = to_24h(t.hour, t.meridiem, t.period)
        return dtime(h % 24, t.minute or 0)
    if t.kind == "period" and t.period:
        h = PERIOD_DEFAULT_HOUR.get(t.period, 18 if t.period == "night" else DEFAULT_CALLBACK_HOUR)
        return dtime(h, 0)
    return None

# ----------------------------------------------------------------------------------------------
# Core resolver: DaySpec + TimeSpec + anchor -> concrete timestamp
# ----------------------------------------------------------------------------------------------
def resolve_expression(call_dt: datetime, day: DaySpec, time: TimeSpec) -> Resolution:
    call_dt = call_dt.astimezone(IST)
    today = call_dt.date()

    # F10: "in N minutes/hours" resolves from call_started_at, seconds preserved
    if time.kind in ("in_n_minutes", "in_n_hours") and day.kind in ("none", "today"):
        if not time.n or time.n <= 0: return Resolution("vague", reason="interval without positive n")
        delta = timedelta(minutes=time.n) if time.kind == "in_n_minutes" else timedelta(hours=time.n)
        return Resolution("resolved", call_dt + delta, "interval")

    tod = _time_of_day(time)
    clock = tod or dtime(DEFAULT_CALLBACK_HOUR, 0)              # F5: agreed day, no time -> 11:00
    k = day.kind

    if k == "unresolved":
        return Resolution("vague", reason="event-only / unresolved reference (F12)")
    if k == "none":
        if tod is None: return Resolution("vague", reason="no day and no time")
        d = today                                               # F5 time only: today if future, else tomorrow
        if datetime.combine(d, clock, IST) <= call_dt: d += timedelta(days=1)
        return Resolution("resolved", datetime.combine(d, clock, IST), "time only")

    explicit_past_check = True
    if k == "today":
        d = today
    elif k == "tomorrow":
        d = today + timedelta(days=1)
    elif k == "day_after_tomorrow":
        d = today + timedelta(days=2)
    elif k == "in_n_days":
        if day.n is None or day.n < 0: return Resolution("vague", reason="in_n_days without n")
        d = today + timedelta(days=day.n)
    elif k == "weekday":
        if day.weekday is None: return Resolution("vague", reason="weekday missing")
        t = WEEKDAYS.index(day.weekday); wd = today.weekday()
        if day.qualifier == "next":                             # following Monday-Sunday week
            d = today - timedelta(days=wd) + timedelta(days=7 + t)
        elif day.qualifier == "this":                           # today or later, with a future time
            d = today + timedelta(days=(t - wd) % 7)
            if datetime.combine(d, clock, IST) <= call_dt: d += timedelta(days=7)
        else:                                                   # no this/next: nearest STRICTLY future
            d = today + timedelta(days=((t - wd) % 7) or 7)
    elif k == "week":
        if day.qualifier == "next": d = today - timedelta(days=today.weekday()) + timedelta(days=7)   # next Monday
        else: return Resolution("vague", reason="'this week' alone is vague (F4)")
    elif k == "in_n_months":
        if not day.n or day.n < 1: return Resolution("vague", reason="in_n_months without n")
        d = add_months(today, day.n)
    elif k == "month":
        if day.qualifier != "next": return Resolution("vague", reason="month reference without 'next'")
        d = add_months(today, 1).replace(day=1)                 # bare next month -> 1st at 11:00 (F11)
    elif k == "absolute_date":
        dom, mo, yr = day.day_of_month, day.month, day.year
        if dom is None: return Resolution("vague", reason="absolute_date without day_of_month")
        try:
            if mo is not None and yr is not None:               # full explicit date
                d = date(yr, mo, dom)
                if d < today: return Resolution("rejected", reason="explicit past full date (F6)")
            elif mo is not None:                                # month/day, no year -> next future occurrence
                d = date(today.year, mo, dom)
                if datetime.combine(d, clock, IST) <= call_dt: d = date(today.year + 1, mo, dom)
            else:                                               # day number only ("after the 26th")
                d = None
                for i in range(0, 14):
                    m_first = add_months(today.replace(day=1), i)
                    if dom <= calendar.monthrange(m_first.year, m_first.month)[1]:
                        cand = date(m_first.year, m_first.month, dom)
                        if datetime.combine(cand, clock, IST) > call_dt: d = cand; break
                if d is None: return Resolution("vague", reason="could not place day-of-month")
        except ValueError:
            return Resolution("vague", reason="invalid calendar date")
    else:
        return Resolution("vague", reason=f"unsupported day kind {k}")

    dt = datetime.combine(d, clock, IST)
    if dt <= call_dt:                                           # F6/F9: never silently repair a past time
        return Resolution("rejected", reason="resolved time is not in the future (F6/F9)")
    return Resolution("resolved", dt, k)

def resolve_candidates(call_dt: datetime, cands: List[TimeCandidate]) -> Resolution:
    """F10: accepted alternatives / two-date window -> earliest future date/time."""
    if not cands: return Resolution("vague", reason="no candidates")
    rs = [resolve_expression(call_dt, c.day, c.time) for c in cands]
    ok = [r for r in rs if r.status == "resolved"]
    if ok: return min(ok, key=lambda r: r.dt)
    if any(r.status == "vague" for r in rs): return next(r for r in rs if r.status == "vague")
    return rs[0]

# ----------------------------------------------------------------------------------------------
# next_call_at decision (F2, F3, F7, F8, F9, F12)
# ----------------------------------------------------------------------------------------------
def _fallback(call_dt: datetime, days: int) -> datetime:
    return datetime.combine(call_dt.astimezone(IST).date() + timedelta(days=days),
                            dtime(DEFAULT_CALLBACK_HOUR, 0), IST)

def decide_next_call(disposition: str, call_dt: datetime,
                     events: List[CallbackEvent]) -> Tuple[Optional[str], dict]:
    """Returns (ISO string | None, trace). `trace` records which rule fired - used in error analysis."""
    trace = {"rule": None, "used_event": None, "notes": []}
    if disposition in ("Invalid Lead", "Not Interested", "Unable to Assess"):
        trace["rule"] = "F2 suppression"; return None, trace

    # Operative events only: acknowledged callbacks + explicit vague postponements. Final one wins (F3/F9).
    ops = []
    for e in sorted(events, key=lambda e: e.order):
        if e.event_type == "callback" and e.status == "agreed" and e.acknowledged == "yes":
            ops.append(e)
        elif e.event_type == "vague_postponement" and e.status in ("agreed", "unacknowledged"):
            ops.append(e)
    final = ops[-1] if ops else None

    result_dt: Optional[datetime] = None
    if final is not None and final.event_type == "callback":
        res = resolve_candidates(call_dt, final.candidates)
        trace["used_event"] = final.raw_phrase
        if res.status == "resolved":
            trace["rule"] = "F3 specific callback"; result_dt = res.dt
        elif res.status == "vague":
            trace["rule"] = "F7 vague (callback unresolvable: " + res.reason + ")"
            result_dt = _fallback(call_dt, VAGUE_FALLBACK_DAYS) if disposition == "Follow-up Required" else None
        else:
            trace["rule"] = "F6 rejected (" + res.reason + ") -> other fallback"
            result_dt = _fallback(call_dt, OTHER_FALLBACK_DAYS) if disposition == "Follow-up Required" else None
    elif final is not None:                                      # explicit vague postponement
        trace["rule"] = "F7 vague postponement"; trace["used_event"] = final.raw_phrase
        result_dt = _fallback(call_dt, VAGUE_FALLBACK_DAYS) if disposition == "Follow-up Required" else None
    else:
        if disposition == "Follow-up Required":
            trace["rule"] = "F8 +1 day fallback"; result_dt = _fallback(call_dt, OTHER_FALLBACK_DAYS)
        else:                                                    # Appointment Scheduled, no distinct callback
            trace["rule"] = "F8 appointment without callback -> null"

    if disposition == "Appointment Scheduled" and not (final is not None and final.event_type == "callback"
                                                       and result_dt is not None and trace["rule"].startswith("F3")):
        result_dt = None                                         # appointments never get vague / +1 fallback
        trace["notes"].append("appointment: only a distinct valid callback may populate next_call_at")

    if result_dt is not None and result_dt <= call_dt.astimezone(IST):   # F9 safety net
        trace["notes"].append("result not in future -> dropped"); result_dt = None
    return (fmt(result_dt) if result_dt else None), trace

# ----------------------------------------------------------------------------------------------
# Consultation offset (used by lead-quality: High needs offset 0-6, Medium if >= 7)
# ----------------------------------------------------------------------------------------------
def consultation_offset_days(call_dt: datetime, day: DaySpec) -> Optional[int]:
    """Calendar-date offset of the consultation from the call date (call date = offset 0). None if unresolvable.
    Time-of-day is irrelevant for the offset, so a dummy mid-day clock is supplied."""
    r = resolve_expression(call_dt, day, TimeSpec(kind="clock", hour=23, minute=59))
    if r.status != "resolved": return None
    return (r.dt.date() - call_dt.astimezone(IST).date()).days
