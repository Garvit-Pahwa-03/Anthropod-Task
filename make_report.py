"""Builds REPORT.md (accuracy, failure patterns, runtime, tokens, cost, environment) from a finished run.
python make_report.py --preds runs/final/preds.jsonl [--out REPORT.md]
Gold labels are used here only to SCORE (never during prediction)."""
import argparse, json, re, sys, platform
from collections import Counter
from datetime import datetime
from importlib import metadata
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--preds", required=True); ap.add_argument("--inputs", default="data/inputs.jsonl")
ap.add_argument("--gold", default="data/gold.jsonl"); ap.add_argument("--split", default="data/split.json")
ap.add_argument("--out", default="REPORT.md")
a = ap.parse_args()
PRICE_IN, PRICE_OUT = 0.15, 0.60            # USD per million tokens, published Groq list price for openai/gpt-oss-120b (verify before quoting)
W = {"disposition": 15, "sub_disposition": 20, "lead_quality": 15, "next_call_at": 20}

ld = lambda p: {json.loads(l)["transcript_id"]: json.loads(l) for l in open(p, encoding="utf-8") if l.strip()}
raw_lines = [json.loads(l) for l in open(a.preds, encoding="utf-8") if l.strip()]
pred, gold, inp = ld(a.preds), ld(a.gold), ld(a.inputs)
dbg = ld(a.preds + ".debug.jsonl") if Path(a.preds + ".debug.jsonl").exists() else {}
run = json.load(open(a.preds + ".run.json")) if Path(a.preds + ".run.json").exists() else {}
split = json.load(open(a.split)) if Path(a.split).exists() else {"dev": [], "holdout": []}
out = []; P = out.append

# ---- output contract check -----------------------------------------------------------------------------
KEYS = {"transcript_id", "disposition", "sub_disposition", "lead_quality", "next_call_at"}
iso = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+05:30$")
ids = [r["transcript_id"] for r in raw_lines]
contract = {"records in file": len(raw_lines), "duplicate ids": len(ids) - len(set(ids)),
            "missing vs gold ids": len(set(gold) - set(ids)), "records with keys != the 5 required": sum(set(r) != KEYS for r in raw_lines),
            "bad next_call_at format": sum(r["next_call_at"] is not None and not iso.match(str(r["next_call_at"])) for r in raw_lines)}

def score(idlist):
    n = len(idlist)
    if not n: return None
    f = {k: 0 for k in W}; ex = 0
    for i in idlist:
        p, g = pred[i], gold[i]; d = p["disposition"] == g["disposition"]
        r = {"disposition": d, "sub_disposition": d and p["sub_disposition"] == g["sub_disposition"],
             "lead_quality": p["lead_quality"] == g["lead_quality"], "next_call_at": p["next_call_at"] == g["next_call_at"]}
        for k, v in r.items(): f[k] += v
        ex += all(r.values())
    est = sum(f[k] / n * w for k, w in W.items())
    return n, f, ex, est

scored = [i for i in pred if i in gold]
groups = {"ALL labeled records": scored, "dev (used for prompt development)": [i for i in scored if i in set(split["dev"])],
          "holdout (never used to choose prompts)": [i for i in scored if i in set(split["holdout"])]}

P(f"# Results report\n\nGenerated {datetime.now():%Y-%m-%d %H:%M} from `{a.preds}`\n")
P("## 1. Accuracy against the 50 labeled calls\n")
P("| subset | n | disposition | sub_disposition (needs parent) | lead_quality | next_call_at | whole-record exact | est. score /70 |\n|---|---|---|---|---|---|---|---|")
for name, idl in groups.items():
    s = score(idl)
    if s: n, f, ex, est = s; P(f"| {name} | {n} | {f['disposition']/n:.1%} | {f['sub_disposition']/n:.1%} | {f['lead_quality']/n:.1%} | {f['next_call_at']/n:.1%} | {ex/n:.1%} ({ex}/{n}) | {est:.1f} |")
P("\nWith n=12 (holdout) one record is 8 percentage points, and the model is not perfectly repeatable between runs, so differences of a few points are noise. "
  "The estimated score is the assignment's weights applied to these accuracies; the private-set score will differ.\n")
maj = Counter(gold[i]["sub_disposition"] for i in scored).most_common(1)[0]
P(f"Reference points: always predicting the most common disposition scores {Counter(gold[i]['disposition'] for i in scored).most_common(1)[0][1]/len(scored):.0%} on disposition; "
  f"always predicting `{maj[0]}` scores {maj[1]/len(scored):.0%} on sub_disposition.\n")

P("## 2. Output contract check\n"); [P(f"- {k}: **{v}**") for k, v in contract.items()]

P("\n## 3. Failure patterns\n")
conf = Counter((gold[i]["sub_disposition"], pred[i]["sub_disposition"]) for i in scored if pred[i]["disposition"] == gold[i]["disposition"] and pred[i]["sub_disposition"] != gold[i]["sub_disposition"])
dconf = Counter((gold[i]["disposition"], pred[i]["disposition"]) for i in scored if pred[i]["disposition"] != gold[i]["disposition"])
lconf = Counter((gold[i]["lead_quality"], pred[i]["lead_quality"]) for i in scored if pred[i]["lead_quality"] != gold[i]["lead_quality"])
def gap(i, v):
    if v is None: return "null"
    return f"+{(datetime.fromisoformat(v).date() - datetime.fromisoformat(inp[i]['call_started_at']).date()).days}d"
nconf = Counter((gap(i, gold[i]["next_call_at"]) + (" " + gold[i]["next_call_at"][11:16] if gold[i]["next_call_at"] else ""),
                 gap(i, pred[i]["next_call_at"]) + (" " + pred[i]["next_call_at"][11:16] if pred[i]["next_call_at"] else "")) for i in scored if pred[i]["next_call_at"] != gold[i]["next_call_at"])
for title, c, hdr in [("disposition (gold -> predicted)", dconf, "gold -> predicted"), ("sub_disposition within the correct parent (gold -> predicted)", conf, ""),
                      ("lead_quality (gold -> predicted)", lconf, ""), ("next_call_at (gold gap/time -> predicted gap/time, relative to call date)", nconf, "")]:
    P(f"**{title}**\n")
    P("\n".join(f"- {g} -> {p}: {n}" for (g, p), n in c.most_common()) if c else "- none")
    P("")

P("## 4. Every mismatch\n\n| id | wrong fields | predicted | gold | rule that produced next_call_at |\n|---|---|---|---|---|")
for i in scored:
    p, g = pred[i], gold[i]
    bad = [f for f in ("disposition", "sub_disposition", "lead_quality", "next_call_at") if p[f] != g[f]]
    if bad:
        rule = ((dbg.get(i) or {}).get("trace") or {}).get("rule") or ""
        P(f"| {i} | {', '.join(bad)} | {p['sub_disposition']} / {p['lead_quality']} / {p['next_call_at']} | {g['sub_disposition']} / {g['lead_quality']} / {g['next_call_at']} | {rule} |")

P("\n## 5. Runtime, tokens, cost\n")
tin = tout = tre = calls = 0; lat = 0.0; cached = 0
for d in dbg.values():
    for m in (d.get("meta") or {}).values():
        tin += m.get("prompt_tokens", 0); tout += m.get("completion_tokens", 0); tre += m.get("reasoning_tokens", 0)
        calls += m.get("attempts", 0); lat += m.get("latency_s", 0); cached += bool(m.get("cached"))
n = max(len(pred), 1)
P(f"- records: {len(pred)}; model calls (incl. retries): {calls}; calls served from the dev cache: {cached}")
P(f"- tokens (this output file): input **{tin:,}**, output **{tout:,}** (of which hidden reasoning {tre:,}); about {(tin+tout)/n:,.0f} tokens per record")
P(f"- estimated cost: **${tin*PRICE_IN/1e6 + tout*PRICE_OUT/1e6:.3f}** for these {len(pred)} records at ${PRICE_IN}/M input and ${PRICE_OUT}/M output tokens (list price; verify)")
P(f"- sum of per-call model latency: {lat/60:.1f} min; wall-clock of the last session: {run.get('runtime_s', 'n/a')} s "
  f"(parallel workers and rate-limit waits make wall-clock differ from the sum)")
if cached: P("- NOTE: some calls were replayed from the dev cache, so token totals above include their original usage only if the cache was warmed in this run.")

P("\n## 6. Configuration of this run\n")
s = run.get("settings", {})
for k in ("model", "temperature", "reasoning_effort", "max_completion_tokens", "timeout", "max_attempts", "seed", "api_keys_in_pool"):
    P(f"- {k}: `{s.get(k, run.get(k, 'n/a'))}`")
P(f"- prompt version: `{run.get('prompt_version', 'n/a')}`; strict JSON-schema mode at end of run: `{run.get('strict_schema_mode_at_end', 'n/a')}`")
P("\n## 7. Environment\n")
P(f"- Python {platform.python_version()} on {platform.system()}")
for pkg in ("groq", "pydantic", "python-dotenv", "pandas", "openpyxl", "jsonschema", "httpx", "pytest", "matplotlib"):
    try: P(f"- {pkg}=={metadata.version(pkg)}")
    except metadata.PackageNotFoundError: pass
Path(a.out).write_text("\n".join(out), encoding="utf-8")
print(f"wrote {a.out}")
