"""A/B comparison of two prediction files against gold (DEV ONLY).
python compare_runs.py runs/base_dev/preds.jsonl runs/vague_dev/preds.jsonl [--split dev]
Reports per-field accuracy for both runs on the records present in BOTH, and lists records that got FIXED or BROKEN."""
import argparse, json
ap = argparse.ArgumentParser(); ap.add_argument("a"); ap.add_argument("b")
ap.add_argument("--gold", default="data/gold.jsonl"); ap.add_argument("--split", choices=["dev", "holdout"])
x = ap.parse_args()
ld = lambda p: {json.loads(l)["transcript_id"]: json.loads(l) for l in open(p, encoding="utf-8") if l.strip()}
A, B, G = ld(x.a), ld(x.b), ld(x.gold)
ids = [i for i in A if i in B and i in G]
if x.split: keep = set(json.load(open("data/split.json"))[x.split]); ids = [i for i in ids if i in keep]

def ok(p, g):
    d = p["disposition"] == g["disposition"]
    return {"disposition": d, "sub_disposition": d and p["sub_disposition"] == g["sub_disposition"],
            "lead_quality": p["lead_quality"] == g["lead_quality"], "next_call_at": p["next_call_at"] == g["next_call_at"]}
W = {"disposition": 15, "sub_disposition": 20, "lead_quality": 15, "next_call_at": 20}
RA = {i: ok(A[i], G[i]) for i in ids}; RB = {i: ok(B[i], G[i]) for i in ids}
n = len(ids); print(f"records compared: {n}\n")
print(f"{'field':18s}{'A':>8s}{'B':>8s}{'change':>9s}")
sa = sb = 0
for f, w in W.items():
    a, b = sum(RA[i][f] for i in ids), sum(RB[i][f] for i in ids); sa += a / n * w; sb += b / n * w
    print(f"{f:18s}{a:>5d}/{n}{b:>5d}/{n}{b - a:>+9d}")
ea = sum(all(RA[i].values()) for i in ids); eb = sum(all(RB[i].values()) for i in ids)
print(f"{'whole-record exact':18s}{ea:>5d}/{n}{eb:>5d}/{n}{eb - ea:>+9d}")
print(f"\nestimated score /70:  A={sa:.1f}  B={sb:.1f}  ({sb - sa:+.1f})")
for f in W:
    fixed = [i for i in ids if not RA[i][f] and RB[i][f]]; broken = [i for i in ids if RA[i][f] and not RB[i][f]]
    if fixed or broken: print(f"\n[{f}]  fixed: {fixed or '-'}   broken: {broken or '-'}")
