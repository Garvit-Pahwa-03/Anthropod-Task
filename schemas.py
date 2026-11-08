"""Intermediate schemas the LLM fills. The LLM answers evidence questions; policy.py decides the labels."""
import copy
from typing import List, Literal, Type
from pydantic import BaseModel
from temporal import DaySpec, CallbackEvent

Blocker = Literal["Family Discussion", "Cost Concern", "Travel Constraint", "Current Treatment", "Treatment Concern"]

class JourneyExtraction(BaseModel):
    """Call A - journey state. Field ORDER matters: the short rationale is generated before the answers."""
    rationale: str                                           # <= 60 words, plain language
    clinic_agent_label: Literal["Agent", "Customer", "unclear"]   # which printed label is really the clinic agent
    intended_patient: Literal["self", "family_member", "unclear"]
    meaningful_pain_discussion: bool
    wrong_contact: bool
    no_pain_need: bool
    test_enquiry: bool
    patient_under_15_known: bool
    outside_service_area_permanent: bool
    final_stance: Literal["none", "explicit_refusal", "do_not_contact"]
    final_stance_lines: List[int]
    consultation_commitment: Literal["confirmed_slot", "day_commitment_only", "tentative_or_none"]
    consultation_modality: Literal["clinic", "online", "unclear"]
    consultation_replaces_existing_or_missed: bool
    consultation_has_clock_time_or_window: bool
    consultation_day: DaySpec
    consultation_lines: List[int]
    open_blockers: List[Blocker]
    blocker_lines: List[int]
    final_next_step_is_review_of_information: bool
    need_established: bool
    exploratory_curiosity_only: bool
    need_or_willingness_unreliable: bool
    defers_more_than_30_days: bool

class EventsExtraction(BaseModel):
    """Call B - scheduling events (callbacks, vague postponements, and look-alikes)."""
    events: List[CallbackEvent]

def strict_schema(model: Type[BaseModel]) -> dict:
    """Pydantic -> JSON Schema that satisfies strict structured-output rules:
    refs inlined, additionalProperties=false, every property required (optional = nullable)."""
    s = model.model_json_schema()
    defs = s.pop("$defs", {})
    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(copy.deepcopy(defs[node["$ref"].split("/")[-1]]))
            out = {k: walk(v) for k, v in node.items() if k not in ("title", "default")}
            if "properties" in out:
                out["additionalProperties"] = False
                out["required"] = list(out["properties"].keys())
            return out
        if isinstance(node, list): return [walk(x) for x in node]
        return node
    return walk(s)
