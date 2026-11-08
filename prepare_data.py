"""Step 1: load the workbook, split INPUTS from GOLD (leakage safeguard), profile the data.

Usage:  python prepare_data.py "path/to/FDE_Hiring_Assignment...xlsx"
Writes: data/inputs.jsonl  (4 input fields only)
        data/gold.jsonl    (id + 4 gold labels; used ONLY by evaluate.py)
        data/split.json    (deterministic dev / holdout ids)
"""
import json, re, sys
from collections import Counter
from datetime import datetime
import pandas as pd
from constants import VALID_PAIRS, LEAD_QUALITIES

path = sys.argv[1] if len(sys.argv) > 1 else "data/workbook.xlsx"
SHEET = "50 Labeled Calls"
INPUT_COLS = ["transcript_id", "call_started_at", "timezone", "transcript"]
GOLD_COLS = ["disposition", "sub_disposition", "lead_quality", "next_call_at"]

# keep_default_na=False is IMPORTANT: the sheet uses the literal text "null" and
# pandas would otherwise silently turn it into NaN.
df = pd.read_excel(path, sheet_name=SHEET, keep_default_na=False, dtype=str)
missing = set(INPUT_COLS + GOLD_COLS) - set(df.columns)
assert not missing, f"missing columns: {missing}"

print(f"rows={len(df)}  unique ids={df.transcript_id.is_unique}  timezones={df.timezone.unique().tolist()}")

# ---- write inputs / gold separately -------------------------------------------------
with open("data/inputs.jsonl", "w", encoding="utf-8") as f:
    for r in df[INPUT_COLS].to_dict("records"):
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

def to_null(x): return None if x.strip().lower() == "null" else x
gold = []
for r in df[["transcript_id"] + GOLD_COLS].to_dict("records"):
    r["next_call_at"] = to_null(r["next_call_at"])
    gold.append(r)
with open("data/gold.jsonl", "w", encoding="utf-8") as f:
    for r in gold: f.write(json.dumps(r, ensure_ascii=False) + "\n")

# ---- validate gold against the policy ------------------------------------------------
bad_pairs = [g["transcript_id"] for g in gold
             if g["sub_disposition"] not in VALID_PAIRS.get(g["disposition"], [])]
bad_lq = [g["transcript_id"] for g in gold if g["lead_quality"] not in LEAD_QUALITIES]
iso = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+05:30$")
bad_ts = [g["transcript_id"] for g in gold if g["next_call_at"] and not iso.match(g["next_call_at"])]
print("invalid pairs:", bad_pairs, "| invalid lead_quality:", bad_lq, "| bad timestamps:", bad_ts)

# ---- profile --------------------------------------------------------------------------
g = pd.DataFrame(gold)
print("\nDisposition / sub_disposition / lead_quality:")
print(g.groupby(["disposition", "sub_disposition", "lead_quality"]).size().to_string())
print("\nnext_call_at null:", g.next_call_at.isna().sum(), "of", len(g))

# gap between call time and gold next_call_at, in days/hours -> reveals which rules dominate
meta = df.set_index("transcript_id").call_started_at
rows = []
for r in gold:
    if r["next_call_at"]:
        t0 = datetime.fromisoformat(meta[r["transcript_id"]])
        t1 = datetime.fromisoformat(r["next_call_at"])
        rows.append((r["transcript_id"], r["disposition"], (t1.date() - t0.date()).days,
                     t1.strftime("%H:%M:%S")))
gap = pd.DataFrame(rows, columns=["id", "disp", "day_gap", "clock"])
print("\nday gap between call date and next_call_at:\n", gap.day_gap.value_counts().sort_index().to_string())
print("\nclock times:\n", gap.clock.value_counts().to_string())

print("\nTranscript length (chars):", df.transcript.str.len().describe()[["min", "mean", "max"]].round().to_dict(),
      "| rough tokens/record ~", int(df.transcript.str.len().mean() / 3.2))

# ---- deterministic stratified dev / holdout split (seeded by sort order, no randomness) -
order = g.sort_values(["disposition", "sub_disposition", "transcript_id"]).reset_index(drop=True)
order["rank_in_group"] = order.groupby(["disposition", "sub_disposition"]).cumcount()
# every 3rd record inside each (disposition, sub_disposition) group goes to holdout
order["split"] = order.rank_in_group.map(lambda i: "holdout" if i % 3 == 2 else "dev")
split = {s: sorted(order[order.split == s].transcript_id) for s in ["dev", "holdout"]}
json.dump(split, open("data/split.json", "w"), indent=2)
print(f"\nsplit -> dev={len(split['dev'])}  holdout={len(split['holdout'])}")
print("Singleton classes (cannot be split): ",
      [k for k, v in Counter(zip(g.disposition, g.sub_disposition)).items() if v < 3])
