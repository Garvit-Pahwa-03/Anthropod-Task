"""Error-analysis helper: python inspect_record.py AVT-005 runs/v1_dev/preds.jsonl
Shows gold vs prediction, the model's rationale and flags, the scheduling events, the rule that fired,
and the transcript lines the model cited as evidence."""
import json, sys
tid, preds = sys.argv[1], sys.argv[2]
ld = lambda p: {json.loads(l)["transcript_id"]: json.loads(l) for l in open(p, encoding="utf-8") if l.strip()}
pred, gold, inp, dbg = ld(preds), ld("data/gold.jsonl"), ld("data/inputs.jsonl"), ld(preds + ".debug.jsonl")
lines = [l.strip() for l in inp[tid]["transcript"].replace("\r\n", "\n").split("\n") if l.strip()]
p, g, d = pred[tid], gold[tid], dbg[tid]
print(f"=== {tid}   call_started_at={inp[tid]['call_started_at']}")
for f in ("disposition", "sub_disposition", "lead_quality", "next_call_at"):
    print(f"  {f:16s} pred={p[f]!s:32s} gold={g[f]!s:32s} {'ok' if p[f] == g[f] else '<-- MISMATCH'}")
j = d.get("journey")
if j:
    print("\nrationale:", j["rationale"])
    on = {k: v for k, v in j.items() if v not in (False, [], "none", "unclear", "tentative_or_none", None) and k not in ("rationale",) and not k.endswith("_lines")}
    print("non-default journey fields:", json.dumps(on, ensure_ascii=False))
print("\nevents:")
for e in d.get("events", []): print("  ", json.dumps({k: e[k] for k in ("order", "event_type", "proposer", "acknowledged", "status", "raw_phrase", "evidence_lines")}, ensure_ascii=False),
                                  "|", [ (c["day"]["kind"], c["day"].get("weekday"), c["time"]["kind"], c["time"].get("hour")) for c in e["candidates"]])
print("\nrule fired:", (d.get("trace") or {}).get("rule"), "| notes:", d.get("notes"))
cited = sorted({x for k in ("final_stance_lines", "consultation_lines", "blocker_lines") for x in (j or {}).get(k, [])} |
               {x for e in d.get("events", []) for x in e["evidence_lines"]})
print("\ncited transcript lines:")
for i in cited:
    if 1 <= i <= len(lines): print(f"  [{i}] {lines[i-1][:260]}")
print(f"\n(last 6 lines of {len(lines)})"); [print(f"  [{len(lines)-5+k}] {l[:200]}") for k, l in enumerate(lines[-6:])]
