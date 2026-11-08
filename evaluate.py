"""Score predictions against gold (DEV USE ONLY - the prediction path never reads gold).
python evaluate.py --preds runs/dev/preds.jsonl [--split dev|holdout]"""
import argparse, json
from collections import Counter
import pandas as pd

ap = argparse.ArgumentParser()
ap.add_argument("--preds", required=True); ap.add_argument("--gold", default="data/gold.jsonl")
ap.add_argument("--split", choices=["dev", "holdout"]); ap.add_argument("--show", type=int, default=40)
ap.add_argument("--ok-only", action="store_true", help="skip records whose model calls failed (use after rate-limit trouble)")
a = ap.parse_args()

load = lambda p: {json.loads(l)["transcript_id"]: json.loads(l) for l in open(p, encoding="utf-8") if l.strip()}
pred, gold = load(a.preds), load(a.gold)
dbg = {}
try: dbg = {json.loads(l)["transcript_id"]: json.loads(l) for l in open(a.preds + ".debug.jsonl", encoding="utf-8")}
except FileNotFoundError: pass
ids = [i for i in pred if i in gold]
if a.ok_only: ids = [i for i in ids if not any('failed' in n for n in dbg.get(i, {}).get('notes', []))]
if a.split: keep = set(json.load(open("data/split.json"))[a.split]); ids = [i for i in ids if i in keep]

rows = []
for i in ids:
    p, g = pred[i], gold[i]
    rows.append({"id": i,
                 "disp": p["disposition"] == g["disposition"],
                 "pair": p["disposition"] == g["disposition"] and p["sub_disposition"] == g["sub_disposition"],
                 "sub": p["sub_disposition"] == g["sub_disposition"],
                 "lq": p["lead_quality"] == g["lead_quality"],
                 "next": p["next_call_at"] == g["next_call_at"]})
df = pd.DataFrame(rows).set_index("id")
df["exact"] = df[["disp", "pair", "lq", "next"]].all(axis=1)
n = len(df)
w = {"disp": 15, "pair": 20, "lq": 15, "next": 20}
print(f"\nrecords scored: {n}" + (f"  (split={a.split})" if a.split else ""))
print(pd.DataFrame({"accuracy": df[["disp", "pair", "lq", "next", "exact"]].mean().round(3),
                    "correct": df[["disp", "pair", "lq", "next", "exact"]].sum()}).rename(
    index={"disp": "disposition", "pair": "sub_disposition (needs parent)", "lq": "lead_quality",
           "next": "next_call_at", "exact": "WHOLE-RECORD EXACT"}).to_string())
print("\nestimated automated score (out of 70): %.1f" % sum(df[k].mean() * v for k, v in w.items()))

print("\n--- mismatches ---")
shown = 0
for i in ids:
    r = df.loc[i]
    if r.exact: continue
    p, g = pred[i], gold[i]
    diffs = []
    for f in ("disposition", "sub_disposition", "lead_quality", "next_call_at"):
        if p[f] != g[f]: diffs.append(f"{f}: pred={p[f]!s} | gold={g[f]!s}")
    tr = (dbg.get(i, {}).get("trace") or {}).get("rule")
    print(f"{i}: " + " || ".join(diffs) + (f"   [rule: {tr}]" if tr else ""))
    shown += 1
    if shown >= a.show: print("..."); break

pairs = Counter((gold[i]["sub_disposition"], pred[i]["sub_disposition"]) for i in ids if gold[i]["sub_disposition"] != pred[i]["sub_disposition"])
if pairs:
    print("\n--- sub_disposition confusions (gold -> pred : count) ---")
    for (g, p), c in pairs.most_common(): print(f"  {g} -> {p} : {c}")
