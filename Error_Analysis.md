# Error analysis and iteration log

Policy version `assignment-v2` · model `openai/gpt-oss-120b` (Groq) · temperature 0.0 · reasoning effort medium · seed 7 · prompt version `v1+unreliable+vague`

All numbers below come from `REPORT.md` and `python evaluate.py` on `runs/final/preds.jsonl`. Scores are *estimates*: the assignment's weights (15/20/15/20) applied to accuracy on the labeled calls. The private-set score will differ.

## 1. Results

| subset | n | disposition | sub_disposition (needs parent) | lead_quality | next_call_at | whole-record exact | est. /70 |
|---|---|---|---|---|---|---|---|
| all labeled | 50 | 94.0% (47) | 70.0% (35) | 90.0% (45) | 76.0% (38) | 58.0% (29) | 56.8 |
| dev (used to develop prompts) | 38 | 92.1% | 63.2% | 89.5% | 73.7% | 52.6% (20/38) | 54.6 |
| holdout (not used to choose prompts) | 12 | 100% | 91.7% | 91.7% | 83.3% | 75.0% (9/12) | 63.8 |

Baselines: always predicting the most common disposition scores 72% on disposition; always predicting `Travel Constraint` scores 28% on sub_disposition.

**How to read the dev/holdout gap.** The holdout was *not worse* than dev, which is what we want to see. But n=12 means one record is 8 points on a field, and the model is not repeatable run-to-run (section 5). I do not claim this proves the absence of overfitting. I claim only that no gap in the wrong direction was observed on a small sample. Also note that I had read all 50 gold labels and about 25 transcripts before the split existed (section 6), so the holdout is held out from *tuning*, not from my prior exposure. The private set is the only fully unseen test.

**Output contract.** 50 records, 50 unique IDs, exactly five keys each, every sub_disposition valid for its parent, every timestamp matches `YYYY-MM-DDTHH:MM:SS+05:30`, nulls are JSON null, no Not Interested record has a next_call_at.

## 2. System in one paragraph

Two LLM calls per record. Call A (journey) answers evidence questions (is there a refusal, was a slot mutually confirmed, which blockers are open, is the need established). Call B (events) lists callbacks, vague postponements and look-alikes as structured events. The model never writes a label or a timestamp. `policy.py` applies the published precedence, tie-breaks, valid-pair check and lead-quality order. `temporal.py` resolves dates in fixed +05:30 from `call_started_at` (rules F1-F12; 68 unit tests incl. EX1-EX5). 135 offline tests pass. Gold labels live in a separate file that only `evaluate.py` reads.

## 3. Failure patterns (21 of 50 records have at least one wrong field)

### 3.1 Blocker selection: 15 sub_disposition errors, the largest group
15 sub_disposition errors in total: 12 are confusions within the correct parent and 3 come from a wrong disposition (3.3, 3.4). The 12 within-parent confusions: Travel Constraint predicted as Family Discussion (4: AVT-001, 020, 040, 048), Travel Constraint as Specific Callback (1: AVT-017) or Further Discussion (1: AVT-050), Cost Concern as Family Discussion (1: AVT-049), Current Treatment as Cost Concern (AVT-038), Treatment Concern as Travel Constraint (AVT-047), Vague Deferral as Cost Concern (AVT-032), Information Requested as Specific Callback (AVT-013), Family Discussion as Information Requested (AVT-034).

**Cause, confirmed in the code.** `policy.py` takes the first label in the published tie-break order (Family Discussion, Cost Concern, Travel Constraint, Current Treatment, Treatment Concern) whenever the model lists more than one open blocker. The policy's tie-break is meant only for several reasons that are *equally primary*; otherwise the customer's final explicitly primary reason wins. Seven of the twelve errors (AVT-001, 020, 040, 048, 049, 038, 047) were predicted as a label that comes *earlier* in the tie-break order than the gold label, which is the direction this code path produces. The other five have a different mechanism: where the model lists no open blocker at all, `policy.py` falls through to Specific Callback, Information Requested, Vague Deferral or Further Discussion, so a missed blocker becomes one of those (AVT-017, 050, 013, 034). AVT-032 is the reverse case: the model listed Cost Concern where gold sees no dominating blocker.

Fix, **not implemented**: ask the model for one *primary* blocker and a separate tie flag, and apply the tie-break only when it flags a genuine tie. This was identified after the holdout run and the prompts were frozen (section 8). `python inspect_record.py <ID> runs/final/preds.jsonl` shows the listed blockers per record if you want to verify the seven.

### 3.2 Vague postponement not detected: 6 next_call_at errors of "+3 days expected, +1 day predicted"
AVT-006, 028, 031, 034, 043 and 013. In the first five the events call returned no vague postponement, so F8 (+1 day) fired instead of F7 (+3 days). AVT-013 is different: F3 fired, because the model recorded a specific callback, while gold treats the ending as a vague postponement (and labels it Information Requested). In AVT-028 the customer closes with "I will see then"; in AVT-034 the agent asks the customer to "let me know on WhatsApp whatever your plan is" and the customer says "Sure". Gold treats both as vague postponements. The `vague` prompt change fixed three such cases earlier in development (next_call_at 25 to 28 of 38, none broken) but did not fix these. Closing statements that hand the next step to the customer are the hardest class for the model, and they matter because next_call_at is worth 20 points.

### 3.3 Confirmed appointment judged tentative: 2 records, 3 disposition errors in total with 3.4
AVT-037 and AVT-039 are gold Appointment Scheduled / Clinic Visit / High / null; we predicted Follow-up Required / Further Discussion with the wrong lead quality and a +1 day callback, so all four fields are wrong. In AVT-037 the customer hedges ("don't confirm it") and then says "keep the appointment for 2 o'clock, I'll come"; the model weighed the hedge over the final statement. In AVT-039 the agent booked 10:20 and the customer agreed, but the model called it tentative. D3 requires a mutually confirmed date and time, so the policy layer is working as written; the error is in the model's reading of the final operative statement.

### 3.4 Conditional refusal read as unconditional: AVT-042
Customer: "Only when you tell me will I want it. You're not telling me. Forget it." Gold is Follow-up Required / Treatment Concern / Not Assessable / +1 day. We predicted Not Interested / Explicit Refusal / Low / null. D2 requires an *unconditional* final refusal; this one is conditional on an unanswered question. A wrong disposition cascades into all four fields because of F2 suppression.

### 3.5 Cascading errors
Errors in 3.1 to 3.4 propagate: a missed blocker changes lead quality (AVT-050 predicted High with no blocker; gold Medium), and a wrong disposition changes next_call_at through F2/F8. Disposition errors (3 records) account for the largest per-record loss.

### 3.6 Other
- **AVT-036** (call at 2026-10-12 10:53:30): predicted a callback at 2026-10-12T11:00:00+05:30 by rule F3; gold next_call_at is null (Appointment Scheduled, 2 PM today). The F9 future-time guard is *not* at fault: 11:00 is later than the 10:53:30 call time, so the value is legitimately in the future. The only callback-like phrase in the transcript is the customer asking "should I call you upon reaching?" and the agent answering yes. That is the customer calling the clinic on arrival, which is appointment logistics, not a callback by the clinic, so the error is upstream in the events extraction, which recorded it as an acknowledged callback with no time (hence the 11:00 default). I inferred this from the transcript and the rule trace; `inspect_record.py AVT-036` shows the extracted event. Fix, **not implemented**: tell the events prompt that a customer's promise to call or ring on arrival is not a callback.
- **AVT-022**: lead quality predicted Medium, gold Low.
- **AVT-040**: sub_disposition and next_call_at wrong; F12 treated an event-only reference as vague.
- **Not Assessable**: the final predictions contain zero Not Assessable lead qualities. At least one gold record (AVT-042) is Not Assessable, so the model rarely uses that branch; the `unreliable` prompt change makes it stricter. This branch is only lightly exercised by the 50 labeled calls.

### 3.7 Labels that never appear in the 50 calls
Invalid Lead (all five sub-labels), Unable to Assess, Do Not Contact, Online Consultation and Rescheduled have no labeled examples, so none of the accuracy figures above says anything about them. They are covered by unit tests of the rule engine, not by end-to-end evidence on real calls.

## 4. Iteration log (what changed and why)

| step | change | evidence | outcome |
|---|---|---|---|
| v1 | zero-shot two-call design | first dev attempt hit Groq free-tier limits (200k tokens/day, 8k/min); only 16 records finished | on those 16: disposition 16/16, lead quality 15/16, next_call_at 14/16, 12/16 exact (biased sample) |
| v2 | three prompt edits bundled | on the 4 records finished by both versions: no fixes, 2 regressions | I could not tell which edit hurt, so I made each edit a separate switch (`blockers`, `unreliable`, `vague`) |
| infra | multi-key pool (five accounts, permitted by the hiring team), resume, per-key pacing | dev runs needed more than one key's daily allowance | 38 dev records finished in about 24 min |
| baseline | v1 on dev, all switches off | disposition 35/38, sub 24/38, lead quality 29/38, next_call_at 25/38, exact 12/38 | est. 51.1 |
| `vague` | count "I will let you know"-type closings as vague postponement (policy F7) | next_call_at 25 to 28 (3 fixed, 0 broken) | kept |
| cache fix | removed old-format cache lookups, added a fixed seed | the `vague` run showed lead quality +6 although the journey prompt was unchanged | see section 5 |
| final | `vague` + `unreliable`; `blockers` dropped | chosen on policy grounds (F7, D5/LQ Not Assessable), not on dev score | est. 56.8 on all 50 |

**Dropped:** `blockers` was the most data-driven rewrite (one phrase came from a dev record) and it did not fix the record it was written for.
**Not tested in isolation:** `unreliable` was never run on its own before the final run, so the final run is its first evaluation. In an earlier isolated run (with the cache problem in section 5) it produced no Not Assessable at all, and AVT-042, whose gold is Not Assessable, got Low. The final run shows the same outcome for AVT-042. I kept it because the policy says Not Assessable is for genuinely unreliable evidence and the model over-used it before, but I cannot show from this data that it helped.

## 5. Noise and a methodology bug I found

Comparing the journey extractions of two dev runs that should have been identical (same prompt, supposedly replayed from cache) showed that **17 of 38 records differed**, and 6 records flipped `need_or_willingness_unreliable`. Those 6 flips explained the apparent +6 lead-quality gain of the `vague` run. Cause: my cache fell back to old-format keys and could return a sample from a different earlier run; on top of that the model itself is not deterministic at temperature 0. Fixes: removed legacy cache lookups, added a cache tag so independent samples can be taken on purpose, and set a fixed seed. (`compare_runs.py` compares two runs' final predictions; the journey-level comparison itself was an ad-hoc script that is not included in the repo.)

Consequences I accept: differences of a few records on 38 are within noise, so I based keep/drop decisions on policy text, not dev deltas; and every number in this document is a single sample, not an average.

## 6. Which records influenced development

- Before any split existed, I read all 50 gold labels and roughly 25 transcripts to understand the conventions (for example that Travel Constraint is used broadly).
- After the split, transcript text was read for 10 records during error analysis, 9 in dev and AVT-011 (holdout) which appears only as a date-arithmetic unit test ("tomorrow afternoon" becomes 15:00). It did not influence a prompt.
- Later review of AVT-028, 034, 037, 039 and 042 (all dev) was for diagnosis only; no phrase from them was copied into a prompt.
- No record ID, name, place or date from the data appears in any prompt. No lookups by ID or transcript hash exist anywhere in the code.
- The holdout was run once on the frozen configuration.

## 7. Runtime, tokens, cost

- Final run, 50 records: 111 model calls (50 x 2 plus retries and repair turns), 3 replayed from the dev cache.
- Tokens (this output file): 450,238 input, 113,519 output (87,504 of them hidden reasoning), about 11,275 per record.
- Estimated cost at list price ($0.15/M input, $0.60/M output): **$0.136** for the final run. A single dev pass over 38 records cost roughly $0.10 at the same prices.
- Wall-clock of the last session: about 1,998 s with parallel workers and rate-limit waits. The run was resumed across sessions, so this is not the total elapsed time. Summed per-call latency is not wall-clock either, because calls overlap.
- The run ended in **plain JSON mode, not strict JSON-schema mode** (`strict_schema_mode_at_end: False`): Groq rejected a generated JSON once, the wrapper fell back to embedding the schema in the prompt, validated with Pydantic and used one repair turn.
- **API keys.** Dev and final runs used **five Groq keys from five separate accounts** to get around the free-tier daily token cap; this was agreed with the hiring team. The submitted command (`python run.py --input ... --output ...`) detects every `GROQ_API_KEY`, `GROQ_API_KEY_2` ... `GROQ_API_KEY_5` it finds in the environment or `.env` and rotates over them automatically, so to reproduce the run the evaluator should put five keys in `.env` as in `.env.example`. With only `GROQ_API_KEY` set it uses that single key (`--single-key` forces this). No key is stored in the repository.

## 8. Limitations and what I would do next

1. **A single free-tier key cannot finish 50 records in a day.** The run needs about 565k tokens against a 200k/day allowance per account, and 8k tokens/minute limits one key to roughly one record a minute. Reproducing the run needs the five-key setup in section 7 or a paid-tier key. If every key hits its daily limit the runner stops early, saves finished records and exits with code 2 (re-run with `--resume`); records not yet processed are then missing from the output.
2. **Blocker priority (3.1).** Ask the model for one primary blocker plus a "tie" flag; apply the tie-break only for ties. Expected upside is bounded: at most 7 sub_disposition records out of 50 (the seven confirmed in 3.1), about 3 points on the 70-point scale, and it needs a fresh run to verify.
3. **Vague postponement recall (3.2).** Add synthetic few-shot examples (fixed examples are allowed by the assignment) for closings that hand the decision to the customer. Keep them out of the reported dev score.
4. **Variance.** Majority voting over three journey samples would cut flip errors at three times the journey cost. I did not measure a second independent baseline, so I cannot say how large the effect would be.
5. **AVT-036 (3.6).** Tell the events prompt that a customer's promise to call on arrival is not a callback.
6. **Unseen labels (3.7).** Add synthetic end-to-end transcripts for them.