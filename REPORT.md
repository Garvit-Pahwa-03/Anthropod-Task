# Results report

Generated 2026-11-08 16:59 from `runs/final/preds.jsonl`

## 1. Accuracy against the 50 labeled calls

| subset | n | disposition | sub_disposition (needs parent) | lead_quality | next_call_at | whole-record exact | est. score /70 |
|---|---|---|---|---|---|---|---|
| ALL labeled records | 50 | 94.0% | 70.0% | 90.0% | 76.0% | 58.0% (29/50) | 56.8 |
| dev (used for prompt development) | 38 | 92.1% | 63.2% | 89.5% | 73.7% | 52.6% (20/38) | 54.6 |
| holdout (never used to choose prompts) | 12 | 100.0% | 91.7% | 91.7% | 83.3% | 75.0% (9/12) | 63.8 |

With n=12 (holdout) one record is 8 percentage points, and the model is not perfectly repeatable between runs, so differences of a few points are noise. The estimated score is the assignment's weights applied to these accuracies; the private-set score will differ.

Reference points: always predicting the most common disposition scores 72% on disposition; always predicting `Travel Constraint` scores 28% on sub_disposition.

## 2. Output contract check

- records in file: **50**
- duplicate ids: **0**
- missing vs gold ids: **0**
- records with keys != the 5 required: **0**
- bad next_call_at format: **0**

## 3. Failure patterns

**disposition (gold -> predicted)**

- Appointment Scheduled -> Follow-up Required: 2
- Follow-up Required -> Not Interested: 1

**sub_disposition within the correct parent (gold -> predicted)**

- Travel Constraint -> Family Discussion: 4
- Information Requested -> Specific Callback: 1
- Travel Constraint -> Specific Callback: 1
- Vague Deferral -> Cost Concern: 1
- Family Discussion -> Information Requested: 1
- Current Treatment -> Cost Concern: 1
- Treatment Concern -> Travel Constraint: 1
- Cost Concern -> Family Discussion: 1
- Travel Constraint -> Further Discussion: 1

**lead_quality (gold -> predicted)**

- High -> Medium: 2
- Low -> Medium: 1
- Not Assessable -> Low: 1
- Medium -> High: 1

**next_call_at (gold gap/time -> predicted gap/time, relative to call date)**

- +3d 11:00 -> +1d 11:00: 6
- null -> +1d 11:00: 2
- null -> +0d 11:00: 1
- +2d 11:00 -> +3d 11:00: 1
- +1d 11:00 -> null: 1
- +1d 11:00 -> +3d 11:00: 1

## 4. Every mismatch

| id | wrong fields | predicted | gold | rule that produced next_call_at |
|---|---|---|---|---|
| AVT-001 | sub_disposition | Family Discussion / Medium / 2026-10-20T11:00:00+05:30 | Travel Constraint / Medium / 2026-10-20T11:00:00+05:30 | F7 vague postponement |
| AVT-006 | next_call_at | Current Treatment / Low / 2026-10-17T11:00:00+05:30 | Current Treatment / Low / 2026-10-19T11:00:00+05:30 | F8 +1 day fallback |
| AVT-013 | sub_disposition, next_call_at | Specific Callback / Medium / 2026-10-16T11:00:00+05:30 | Information Requested / Medium / 2026-10-18T11:00:00+05:30 | F3 specific callback |
| AVT-017 | sub_disposition | Specific Callback / Medium / 2026-10-26T11:00:00+05:30 | Travel Constraint / Medium / 2026-10-26T11:00:00+05:30 | F3 specific callback |
| AVT-020 | sub_disposition | Family Discussion / Medium / 2026-10-21T11:00:00+05:30 | Travel Constraint / Medium / 2026-10-21T11:00:00+05:30 | F7 vague postponement |
| AVT-022 | lead_quality | Treatment Concern / Medium / 2026-10-15T11:00:00+05:30 | Treatment Concern / Low / 2026-10-15T11:00:00+05:30 | F7 vague postponement |
| AVT-028 | next_call_at | Cost Concern / Medium / 2026-10-13T11:00:00+05:30 | Cost Concern / Medium / 2026-10-15T11:00:00+05:30 | F8 +1 day fallback |
| AVT-031 | next_call_at | Travel Constraint / Medium / 2026-10-19T11:00:00+05:30 | Travel Constraint / Medium / 2026-10-21T11:00:00+05:30 | F8 +1 day fallback |
| AVT-032 | sub_disposition | Cost Concern / Medium / 2026-10-18T11:00:00+05:30 | Vague Deferral / Medium / 2026-10-18T11:00:00+05:30 | F7 vague postponement |
| AVT-034 | sub_disposition, next_call_at | Information Requested / Medium / 2026-10-13T11:00:00+05:30 | Family Discussion / Medium / 2026-10-15T11:00:00+05:30 | F8 +1 day fallback |
| AVT-036 | next_call_at | Clinic Visit / High / 2026-10-12T11:00:00+05:30 | Clinic Visit / High / None | F3 specific callback |
| AVT-037 | disposition, sub_disposition, lead_quality, next_call_at | Further Discussion / Medium / 2026-10-14T11:00:00+05:30 | Clinic Visit / High / None | F8 +1 day fallback |
| AVT-038 | sub_disposition | Cost Concern / Medium / 2026-10-20T11:00:00+05:30 | Current Treatment / Medium / 2026-10-20T11:00:00+05:30 | F7 vague postponement |
| AVT-039 | disposition, sub_disposition, lead_quality, next_call_at | Further Discussion / Medium / 2026-10-19T11:00:00+05:30 | Clinic Visit / High / None | F8 +1 day fallback |
| AVT-040 | sub_disposition, next_call_at | Family Discussion / Medium / 2026-10-20T11:00:00+05:30 | Travel Constraint / Medium / 2026-10-19T11:00:00+05:30 | F7 vague (callback unresolvable: event-only / unresolved reference (F12)) |
| AVT-042 | disposition, sub_disposition, lead_quality, next_call_at | Explicit Refusal / Low / None | Treatment Concern / Not Assessable / 2026-10-15T11:00:00+05:30 | F2 suppression |
| AVT-043 | next_call_at | Family Discussion / Medium / 2026-10-15T11:00:00+05:30 | Family Discussion / Medium / 2026-10-17T11:00:00+05:30 | F8 +1 day fallback |
| AVT-047 | sub_disposition | Travel Constraint / Medium / 2026-10-15T14:26:01+05:30 | Treatment Concern / Medium / 2026-10-15T14:26:01+05:30 | F3 specific callback |
| AVT-048 | sub_disposition, next_call_at | Family Discussion / Medium / 2026-10-18T11:00:00+05:30 | Travel Constraint / Medium / 2026-10-16T11:00:00+05:30 | F7 vague postponement |
| AVT-049 | sub_disposition | Family Discussion / Medium / 2026-10-21T11:00:00+05:30 | Cost Concern / Medium / 2026-10-21T11:00:00+05:30 | F3 specific callback |
| AVT-050 | sub_disposition, lead_quality | Further Discussion / High / 2026-10-17T11:00:00+05:30 | Travel Constraint / Medium / 2026-10-17T11:00:00+05:30 | F8 +1 day fallback |

## 5. Runtime, tokens, cost

- records: 50; model calls (incl. retries): 111; calls served from the dev cache: 3
- tokens (this output file): input **450,238**, output **113,519** (of which hidden reasoning 87,504); about 11,275 tokens per record
- estimated cost: **$0.136** for these 50 records at $0.15/M input and $0.6/M output tokens (list price; verify)
- sum of per-call model latency: 458.0 min; wall-clock of the last session: 1997.6 s (parallel workers and rate-limit waits make wall-clock differ from the sum)
- NOTE: some calls were replayed from the dev cache, so token totals above include their original usage only if the cache was warmed in this run.

## 6. Configuration of this run

- model: `openai/gpt-oss-120b`
- temperature: `0.0`
- reasoning_effort: `medium`
- max_completion_tokens: `6000`
- timeout: `120.0`
- max_attempts: `5`
- seed: `7`
- api_keys_in_pool: `5`
- prompt version: `v1+unreliable+vague`; strict JSON-schema mode at end of run: `False`
- Groq keys used: **5** separate-account keys (permitted by the hiring team). To reproduce, put them in `.env` as `GROQ_API_KEY`, `GROQ_API_KEY_2` ... `GROQ_API_KEY_5` (see `.env.example`); `run.py` detects and rotates over all of them automatically. With a single key only `GROQ_API_KEY` is needed, but the free tier (200k tokens/day) cannot finish 50 records.

## 7. Environment

- Python 3.11.9 on Windows
- groq==0.37.1
- pydantic==2.14.3
- python-dotenv==1.2.4
- pandas==3.1.1
- openpyxl==3.1.5
- jsonschema==4.26.0
- httpx==0.28.1
- pytest==9.2.0
- matplotlib==3.11.2