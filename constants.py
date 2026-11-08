"""Single source of truth for labels and policy constants (assignment-v2)."""

VALID_PAIRS = {
    "Appointment Scheduled": ["Clinic Visit", "Online Consultation", "Rescheduled"],
    "Follow-up Required": [
        "Specific Callback", "Vague Deferral", "Family Discussion", "Cost Concern",
        "Travel Constraint", "Current Treatment", "Treatment Concern",
        "Information Requested", "Further Discussion",
    ],
    "Not Interested": ["Explicit Refusal", "Do Not Contact"],
    "Invalid Lead": ["Wrong Contact", "No Pain Need", "Outside Service Area",
                     "Policy Exclusion", "Test Enquiry"],
    "Unable to Assess": ["Incomplete Conversation"],
}
DISPOSITIONS = list(VALID_PAIRS)
LEAD_QUALITIES = ["Not Qualified", "Not Assessable", "Low", "Medium", "High"]

# Tie-break orders from rule "All: Tie-breaking"
FOLLOWUP_TIEBREAK = ["Family Discussion", "Cost Concern", "Travel Constraint",
                     "Current Treatment", "Treatment Concern", "Specific Callback",
                     "Information Requested", "Vague Deferral", "Further Discussion"]
INVALID_TIEBREAK = ["Test Enquiry", "Wrong Contact", "No Pain Need",
                    "Policy Exclusion", "Outside Service Area"]

IST_OFFSET_MINUTES = 330          # +05:30, fixed; no tzdata dependency
DEFAULT_CALLBACK_HOUR = 11        # F5: agreed day, no time -> 11:00
VAGUE_FALLBACK_DAYS = 3           # F7
OTHER_FALLBACK_DAYS = 1           # F8
