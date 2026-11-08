# Aster Vale Pain Clinic — transcript labeling (assignment-v2)

Predicts `disposition`, `sub_disposition`, `lead_quality` and `next_call_at` for a call transcript.
**Model:** `openai/gpt-oss-120b` on Groq. **Design:** the LLM answers small evidence questions; deterministic Python applies the published policy.

## Run it (one command)

```bash
pip install -r requirements.txt
export GROQ_API_KEY=gsk_...            # Windows PowerShell:  $env:GROQ_API_KEY="gsk_..."   (or put it in a .env file)
python run.py --input INPUT.jsonl --output PREDICTIONS.jsonl
```
Tested with Python 3.11.9 (Windows). Exact package versions are in `requirements.lock.txt` (also listed in `REPORT.md` §7).

### Using five Groq keys (as in the submitted run)

The submitted predictions were produced with **five Groq keys from five separate accounts**, because one free-tier account (200k tokens/day) cannot finish 50 records.
This was agreed with the hiring team. To reproduce it, copy `.env.example` to `.env` (next to `run.py`) and fill in five different keys:

```
GROQ_API_KEY=gsk_...      # key 1
GROQ_API_KEY_2=gsk_...    # key 2 (a different Groq account)
GROQ_API_KEY_3=gsk_...    # key 3
GROQ_API_KEY_4=gsk_...    # key 4
GROQ_API_KEY_5=gsk_...    # key 5
```
Then run the same single command, `python run.py --input INPUT.jsonl --output PREDICTIONS.jsonl`. `run.py` detects every `GROQ_API_KEY*` variable (from `.env` or the shell; a comma-separated `GROQ_API_KEYS` also works),
and prints `keys in pool: 5` at start. Requests are spread over the keys with per-key rate pacing, and a key that reaches its daily cap is retired for the rest of the run.
Run `python check_keys.py` first to see which keys are picked up and whether each one works (about 100 tokens per key).

* **One key only:** set just `GROQ_API_KEY`. The runner then uses that one key (use a paid/Developer-tier key, or expect it to stop early on the free tier; see *Capacity needed*).
* `--single-key` forces one key even if the others are set.
* The keys change only *which account sends a request*. Prompts, model, settings and outputs are identical. No key is stored in this repository.

`INPUT.jsonl`: one JSON object per line with `transcript_id`, `call_started_at`, `timezone`, `transcript`.
`PREDICTIONS.jsonl`: one object per input, **exactly** `transcript_id, disposition, sub_disposition, lead_quality, next_call_at`
(`next_call_at` is `YYYY-MM-DDTHH:MM:SS+05:30` or JSON `null`). Order follows the input.
Next to the output the runner also writes `*.debug.jsonl` (intermediate evidence per record), `*.run.json` (settings, token usage, runtime) and `*.partial.jsonl` (checkpoint).

**Capacity needed.** About 10–11k tokens per record (2 model calls) — roughly 530k tokens for 50 records, about $0.13 at Groq's list price.
Groq's *free* tier (8k tokens/minute, 200k tokens/day per account for this model) cannot finish 50 records on one key in one day; use a paid/Developer-tier key, or several keys as described above (5 free-tier keys were used for the submitted run).
The runner waits out per-minute limits, and if a daily limit is hit it stops, saves finished records and exits with code 2 (re-run with `--resume`).

## Exact settings

| item | value |
|---|---|
| model ID | `openai/gpt-oss-120b` |
| temperature | `0` |
| seed | `7` (best-effort determinism; dropped automatically if the API rejects it) |
| reasoning effort | `medium` |
| max completion tokens | 6000 per call (doubled up to 16000 if the model returns empty content) |
| output format | strict JSON Schema (`response_format: json_schema, strict: true`); automatic fallback to `json_object` + schema in the prompt if the API rejects the schema |
| request timeout | 120 s |
| retries | up to 5 attempts per call for connection/timeout/5xx/invalid-JSON; per-minute rate limits (429) are waited out using `retry-after` (up to 40 waits) and do not use attempts; daily limits stop the run |
| JSON parsing | Pydantic validation of every response; one automatic "repair" turn on validation failure |
| workers | 2 parallel records with one key; 2 x number of keys (max 10) with several keys (`--workers`) |
| prompt version | `v1+unreliable+vague` (see `prompts.py`) |
| dependency versions | `requirements.lock.txt` (exact) and `REPORT.md` §7 |

If a model call fails permanently, the record is still written (never dropped): journey failure → `Follow-up Required / Further Discussion / Medium`;
events failure → no callback evidence (the +1 day fallback applies). These cases are flagged in `*.debug.jsonl`.

## How it works

```
transcript ──► preprocess (number the lines, add call date + weekday)
                  │
                  ├─► LLM call A "journey"  → JourneyExtraction  (patient validity, final refusal, consultation commitment,
                  │                                               open blockers, readiness flags, cited line numbers)
                  └─► LLM call B "events"   → EventsExtraction   (callbacks / vague postponements, who proposed, acknowledged?,
                                                                  day/time described in a CLOSED vocabulary — never a date)
                  ▼
        policy.py        precedence + valid pairs + tie-breaks + lead quality
        temporal.py      resolves described days/times against call_started_at (fixed +05:30), applies rules F1–F12
```
* The model never writes a timestamp or a label. It reports *what was said*; `temporal.py` does calendar arithmetic (weekdays, "next week", month ends, 11:00 defaults, +1/+3 day fallbacks, seconds preserved for "in N minutes").
* `policy.py` applies: Invalid Lead > Not Interested > Appointment Scheduled > Follow-up Required > Unable to Assess; the published tie-break orders; lead quality order Not Qualified, Not Assessable, Low, High, Medium; and validates every parent/child pair.
* Transcript lines are numbered so the model cites line numbers instead of quoting; out-of-range citations are logged.
* Gold labels are never read by the prediction path (`run.py → pipeline.py → llm.py/policy.py/temporal.py`). `evaluate.py`, `compare_runs.py`, `make_report.py` and `inspect_record.py` read them for scoring only.

## Files

| file | purpose |
|---|---|
| `run.py` | the one-command runner |
| `prompts.py` | **all final prompt templates** (journey, events, user message) and the switchable prompt segments |
| `schemas.py` | intermediate schemas + strict-schema builder |
| `llm.py` | Groq client wrapper: structured output, validation, retries, rate-limit handling, token accounting |
| `policy.py` | deterministic label logic |
| `temporal.py` | deterministic date/time resolver and `next_call_at` decision |
| `constants.py`, `config.py`, `pipeline.py` | label tables, key loading, per-record workflow |
| `prepare_data.py`, `evaluate.py`, `compare_runs.py`, `inspect_record.py`, `make_report.py`, `diagnose.py` | data prep, scoring, A/B comparison, error inspection, report |
| `keypool.py`, `check_keys.py` | multi-key rotation used when several `GROQ_API_KEY*` are set; key-checker helper |
| `tests/` | 135 offline tests: resolver, policy, schemas, retry logic, key pool |
| `01_eda.ipynb` | exploratory data analysis |
| `predictions.jsonl` | predictions for the 50 supplied calls |
| `REPORT.md`, `ERROR_ANALYSIS.md` | accuracy, failure patterns, runtime, tokens, cost |

Run the tests with `python -m pytest -q tests/` (no network or key needed).

## Development-only options (not needed by the evaluator)

`--split dev|holdout`, `--ids`, `--cache-dir`, `--prompt-changes`, `--resume`, `--single-key`. (`--use-key-pool` is accepted but is now a no-op, because pooling is automatic.)
Dev experiments and the final run used the same five-key rotation (`keypool.py`). It only decides *which key sends a request*; it does not change prompts or outputs.
`.env` is git-ignored; no API key is included in this submission.

## Evaluation protocol

* 50 labeled calls split deterministically (`data/split.json`): 38 dev, 12 holdout, stratified by `(disposition, sub_disposition)`.
* Prompts were tuned on dev only, but I had read all 50 gold labels and about 25 transcripts before the split existed, so the holdout is held out from *tuning*, not from my prior exposure (details in `ERROR_ANALYSIS.md` §6). The final configuration was frozen, then run once on all 50; dev and holdout results are reported separately in `REPORT.md`.
* Nine of the 20 valid sub-dispositions never occur in the 50 calls (all Invalid Lead labels, Unable to Assess, Online Consultation, Rescheduled, Do Not Contact), so their rules are covered by unit tests, not by accuracy numbers.

## What changed during development (and why)

1. **Baseline (v1, zero-shot).** Two LLM calls + Python policy. Dev: disposition 92%, sub_disposition 63%, lead_quality 76%, next_call_at 66%, whole-record exact 32% (est. 51/70).
2. **Rate limits.** The first runs hit the free tier's daily token cap and many calls failed silently into defaults. Fixed: failures are classified (per-minute vs per-day), per-minute limits are waited out, daily limits stop the run loudly, and every finished record is checkpointed.
3. **A bundled prompt change (v2) regressed** two of four re-checked records. I split it into three independent switches (`blockers`, `unreliable`, `vague`) so each could be tested alone.
4. **A comparison I initially misread.** A `vague` run appeared to improve lead_quality by 6 records, but that change only touches the events prompt. Comparing the journey extractions of two runs that should have been identical showed that 17 of 38 records differed and 6 flipped `need_or_willingness_unreliable`; those 6 flips explained the apparent gain. Causes: a response-cache fallback that could return a sample from a different earlier run, plus non-determinism of the model itself at temperature 0. Lessons: (a) differences of a few records on 38 are noise; (b) caches must be per-experiment; (c) a fixed `seed` is now sent.
5. **Final configuration** keeps the two switches that follow the policy text — `vague` (the customer saying they will get back without a date is a vague postponement, rule F7) and `unreliable` (Not Assessable only for genuinely unreliable evidence) — and **drops `blockers`**, the most data-driven rewrite, which did not fix the record it was written for.
6. I read transcript text for ten records while writing prompts and tests (nine dev, one holdout used only in a date-arithmetic unit test); no record IDs or transcript-specific content appear in any prompt.