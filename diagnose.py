"""Summarise what went wrong in a run:  python diagnose.py runs/v1_dev/preds.jsonl.debug.jsonl"""
import json, re, sys
from collections import Counter
errs, fails = Counter(), Counter()
rows = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8")]
for d in rows:
    for name, m in (d.get("meta") or {}).items():
        for e in m.get("errors", []): errs[re.sub(r"\d+", "N", e)[:160]] += 1
    for n in d.get("notes", []):
        if "failed" in n: fails[n[:60]] += 1
print(f"{len(rows)} records;", sum(1 for d in rows if any('failed' in n for n in d.get('notes', []))), "had at least one failed model call\n")
print("Most common error messages:"); [print(f"  {c:4d}  {e}") for e, c in errs.most_common(8)]
print("\nFailure notes:"); [print(f"  {c:4d}  {e}") for e, c in fails.most_common()]
