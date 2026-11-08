"""Compare the journey (Call A) and events (Call B) EXTRACTIONS of two runs on the same records. No gold used.
python diff_runs.py runs/base_dev/preds.jsonl runs/vague_dev/preds.jsonl
Reads <preds>.debug.jsonl. For a pair of runs that should have identical journey outputs (journey prompt unchanged and
replayed from cache), any difference here means cache provenance drift or model noise."""
import json, sys
from collections import Counter
SKIP = {"rationale", "final_stance_lines", "consultation_lines", "blocker_lines"}
def load(p):
    rows = (json.loads(l) for l in open(p + ".debug.jsonl", encoding="utf-8") if l.strip())
    return {d["transcript_id"]: d for d in rows}
A, B = load(sys.argv[1]), load(sys.argv[2])
ids = sorted(set(A) & set(B))
fields, recs, ev = Counter(), [], []
for i in ids:
    ja, jb = A[i].get("journey"), B[i].get("journey")
    if not ja or not jb: continue
    d = [k for k in ja if k not in SKIP and ja[k] != jb.get(k)]
    for k in d: fields[k] += 1
    if d: recs.append((i, d))
    if [e.get("event_type") for e in A[i]["events"]] != [e.get("event_type") for e in B[i]["events"]]: ev.append(i)
    ca = A[i].get("meta", {}).get("journey", {}).get("cached"); cb = B[i].get("meta", {}).get("journey", {}).get("cached")
print(f"records compared: {len(ids)}")
print(f"records whose JOURNEY extraction differs: {len(recs)}")
for i, d in recs: print(f"  {i}: {d}")
print("\nfield flip counts:", dict(fields.most_common()))
print(f"\nrecords whose EVENT TYPES differ: {len(ev)} {ev}")