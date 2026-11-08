"""One command:  python run.py --input INPUT.jsonl --output PREDS.jsonl
Reads GROQ_API_KEY from the environment (or .env). If GROQ_API_KEY_2, GROQ_API_KEY_3 ... (or GROQ_API_KEYS) are
also set, all keys are used automatically as a rotation pool (permitted for this submission); with only GROQ_API_KEY the
runner uses that single key. Writes exactly five keys per line to PREDS.jsonl, plus
<output>.debug.jsonl (intermediate evidence), <output>.run.json (settings, token usage, runtime) and
<output>.partial.jsonl (checkpoint: every finished record is saved immediately, so nothing is lost and --resume can continue).

DEV-ONLY options (never needed by the evaluator): --single-key, --resume, --split, --ids, --cache-dir, --prompt-changes."""
import argparse, json, re, sys, threading, time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from keypool import KeyPool, DailyLimitReached
from llm import GroqExtractor, DEFAULT_MODEL
from pipeline import process_record
from prompts import build_prompts, AVAILABLE_CHANGES, DEFAULT_CHANGES

def failed(debug) -> bool:
    return any(("failed" in n) or n.startswith("UNEXPECTED") for n in (debug or {}).get("notes", []))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True); ap.add_argument("--output", required=True)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--reasoning-effort", default="medium", choices=["low", "medium", "high", "none"])
    ap.add_argument("--max-completion-tokens", type=int, default=6000)
    ap.add_argument("--workers", type=int, default=None, help="default: 2 (one key) or 2 x keys (several keys, max 10)")
    ap.add_argument("--tpm-budget", type=int, default=None, help="per-key tokens/minute pacing; default 0 (off) with one key, 7000 with several keys")
    ap.add_argument("--prompt-changes", default=",".join(DEFAULT_CHANGES), help="DEV ONLY: comma list from: " + ",".join(AVAILABLE_CHANGES) + ", or 'none' for the v1 baseline")
    ap.add_argument("--seed", type=int, default=7, help="sampling seed sent to the API (best-effort determinism)")
    ap.add_argument("--limit", type=int, default=None, help="process only the first N records (smoke tests)")
    ap.add_argument("--split", choices=["dev", "holdout"], help="DEV ONLY: restrict to ids in data/split.json")
    ap.add_argument("--ids", help="DEV ONLY: comma-separated transcript_ids")
    ap.add_argument("--cache-dir", default=None, help="DEV ONLY: cache raw model responses to save tokens on reruns")
    ap.add_argument("--single-key", action="store_true", help="use only GROQ_API_KEY even if GROQ_API_KEY_2.. are set")
    ap.add_argument("--use-key-pool", action="store_true", help=argparse.SUPPRESS)   # deprecated no-op: pooling is automatic now
    ap.add_argument("--resume", action="store_true", help="DEV ONLY: skip records already finished in <output>.partial.jsonl")
    a = ap.parse_args()

    recs = [json.loads(l) for l in open(a.input, encoding="utf-8") if l.strip()]
    if a.split: keep = set(json.load(open("data/split.json"))[a.split]); recs = [r for r in recs if r["transcript_id"] in keep]
    if a.ids: keep = set(a.ids.split(",")); recs = [r for r in recs if r["transcript_id"] in keep]
    if a.limit: recs = recs[:a.limit]
    seen = set(); dups = [r["transcript_id"] for r in recs if r["transcript_id"] in seen or seen.add(r["transcript_id"])]
    if dups: print("WARNING duplicate transcript_ids in input:", dups, file=sys.stderr)

    changes = [c for c in a.prompt_changes.split(",") if c]
    sys_j, sys_e, prompt_version = build_prompts(changes)
    print("prompt version:", prompt_version)

    from config import get_groq_keys, get_groq_key
    if a.single_key:
        keys = [get_groq_key()]
    else:
        keys = get_groq_keys()                      # GROQ_API_KEY first, then GROQ_API_KEY_2.. / GROQ_API_KEYS; de-duplicated
    multi = len(keys) > 1
    if multi:
        pool = KeyPool(keys, tpm_budget=7000 if a.tpm_budget is None else a.tpm_budget, ledger_path=".keyledger.json")
    else:
        pool = KeyPool(keys, tpm_budget=a.tpm_budget or 0)
    workers = a.workers or (min(2 * len(pool.keys), 10) if multi else 2)
    print(f"keys in pool: {len(pool.keys)} | workers: {workers} | per-key TPM pacing: {pool.tpm_budget or 'off'}")
    for s_ in pool.summary():
        if s_["exhausted_for_min"]: print(f"  note: {s_['key']} still exhausted for ~{s_['exhausted_for_min']} min (from earlier run)")

    ex = GroqExtractor(model=a.model, reasoning_effort=None if a.reasoning_effort == "none" else a.reasoning_effort,
                       max_completion_tokens=a.max_completion_tokens, seed=a.seed, cache_dir=a.cache_dir, pool=pool)
    out = Path(a.output); out.parent.mkdir(parents=True, exist_ok=True)
    partial_path = Path(str(out) + ".partial.jsonl")

    done = {}                                                # transcript_id -> (pred, debug)
    if a.resume and partial_path.exists():
        for l in partial_path.read_text(encoding="utf-8").splitlines():
            if not l.strip(): continue
            x = json.loads(l)
            if not failed(x["debug"]): done[x["pred"]["transcript_id"]] = (x["pred"], x["debug"])
        print(f"resume: {len(done)} records already finished -> skipped")
    elif partial_path.exists(): partial_path.unlink()
    todo = [r for r in recs if r["transcript_id"] not in done]

    stop = threading.Event(); stop_msg = []; lock = threading.Lock(); t0 = time.time()
    counter = [len(done)]
    pf = open(partial_path, "a", encoding="utf-8")

    def work(r):
        if stop.is_set(): return
        try: res = process_record(r, ex, (sys_j, sys_e))
        except DailyLimitReached as e:
            stop_msg.append(str(e)); stop.set(); return
        except Exception as e:                                # last-resort guard: never lose a record
            res = ({"transcript_id": r.get("transcript_id"), "disposition": "Follow-up Required",
                    "sub_disposition": "Further Discussion", "lead_quality": "Medium", "next_call_at": None},
                   {"transcript_id": r.get("transcript_id"), "notes": [f"UNEXPECTED {type(e).__name__}: {e}"]})
        with lock:
            done[res[0]["transcript_id"]] = res; counter[0] += 1
            pf.write(json.dumps({"pred": res[0], "debug": res[1]}, ensure_ascii=False, default=str) + "\n"); pf.flush()
            p = res[0]; keys = sorted({k for m in (res[1].get("meta") or {}).values() for k in m.get("keys", [])})
            print(f"[{counter[0]}/{len(recs)}] {p['transcript_id']}  {p['disposition']} / {p['sub_disposition']} / {p['lead_quality']} / {p['next_call_at']}"
                  + (f"   via {','.join(k.split('(')[0] for k in keys)}" if len(pool.keys) > 1 and keys else "")
                  + ("  !! " + "; ".join(res[1].get("notes", [])) if res[1].get("notes") else ""), flush=True)

    with ThreadPoolExecutor(max_workers=workers) as tp: list(tp.map(work, todo))
    pf.close()

    results = [done[r["transcript_id"]] for r in recs if r["transcript_id"] in done]
    with open(out, "w", encoding="utf-8") as f:
        for p, _ in results: f.write(json.dumps(p, ensure_ascii=False) + "\n")
    with open(str(out) + ".debug.jsonl", "w", encoding="utf-8") as f:
        for _, d in results: f.write(json.dumps(d, ensure_ascii=False, default=str) + "\n")

    tot = {"prompt_tokens": 0, "completion_tokens": 0, "reasoning_tokens": 0, "attempts": 0}; errs = Counter()
    for _, d in results:
        for m in (d.get("meta") or {}).values():
            for k in tot: tot[k] += m.get(k, 0)
            for e in m.get("errors", []): errs[re.sub(r"\d+", "N", e)[:90]] += 1
    tot["failed_records"] = sum(1 for _, d in results if failed(d))
    json.dump({"model": a.model, "settings": ex.settings, "prompt_version": prompt_version, "records": len(results),
               "requested_records": len(recs), "runtime_s": round(time.time() - t0, 1), "usage_this_session": tot,
               "strict_schema_mode_at_end": ex.strict, "stopped_early": bool(stop_msg),
               "error_summary": dict(errs.most_common(10)), "key_pool": pool.summary()},
              open(str(out) + ".run.json", "w"), indent=2)
    print(f"\nwrote {out}  | {len(results)}/{len(recs)} records | tokens this session in={tot['prompt_tokens']:,} out={tot['completion_tokens']:,} "
          f"(reasoning {tot['reasoning_tokens']:,}) | {time.time()-t0:.0f}s | failed records: {tot['failed_records']}")
    if len(pool.keys) > 1:
        print("per-key usage:"); [print(f"  {s['key']}: {s['tokens']:,} tokens, {s['calls']} calls, daily-limit hits {s['daily_limit_hits']}") for s in pool.summary()]
    if errs: print("error summary:", dict(errs.most_common(5)))
    if stop_msg:
        print(f"\n*** STOPPED EARLY after {len(results)}/{len(recs)} records. ***\n{stop_msg[0][:600]}\n"
              f"Finished records are saved. Re-run the SAME command with --resume (and --cache-dir) once a key resets.", file=sys.stderr)
        sys.exit(2)

if __name__ == "__main__":
    main()