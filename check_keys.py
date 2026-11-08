"""DEV helper: shows which Groq keys are being picked up and whether each one works.
python check_keys.py            # parse .env + live test of every key (uses ~100 tokens per key)
python check_keys.py --no-call  # only parse, no API calls"""
import os, re, sys
from pathlib import Path

EXPECTED = re.compile(r"^GROQ_API_KEY(_?\d+)?$|^GROQ_API_KEYS$")

def parse_env_file(path: Path):
    """Returns [(line_no, name, value, problems)] for every assignment-looking line in .env (values are not printed)."""
    rows = []
    for n, raw in enumerate(path.read_text(encoding="utf-8-sig", errors="replace").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"): continue
        if "=" not in line: rows.append((n, line[:20], "", ["no '=' on this line"])); continue
        name, value = line.split("=", 1)
        problems = []
        if name.strip().lower().startswith("export "): problems.append("remove the 'export' prefix")
        name = name.replace("export ", "").strip()
        v = value.strip()
        if " #" in v: problems.append("inline comment after the value")
        v = v.split(" #")[0].strip().strip('"').strip("'")
        if "GROQ" in name.upper() and not EXPECTED.match(name): problems.append("name not recognised (use GROQ_API_KEY_2, GROQ_API_KEY_3 ...)")
        if EXPECTED.match(name) and not v: problems.append("EMPTY value")
        if EXPECTED.match(name) and v and not v.startswith("gsk_"): problems.append("value does not start with gsk_")
        rows.append((n, name, v, problems))
    return rows

def main():
    env_path = Path(__file__).resolve().parent / ".env"
    print(f".env location: {env_path}  exists={env_path.exists()}")
    if env_path.exists():
        print("\nlines read from .env (values hidden):")
        rows = parse_env_file(env_path)
        lens = [len(v) for _, nm, v, _ in rows if EXPECTED.match(nm) and v]
        common = max(set(lens), key=lens.count) if lens else 0
        for n, name, v, problems in rows:
            if EXPECTED.match(name) and v and len(v) != common: problems = problems + [f"length {len(v)} differs from the usual {common} - stray character?"]
            print(f"  line {n:2d}  {name:18s} value_len={len(v):3d}  " + ("  <-- " + "; ".join(problems) if problems else "ok"))
    else:
        print("  -> no .env next to this script. Create it there (same folder as config.py).")

    from config import get_groq_keys
    try: keys = get_groq_keys()
    except Exception as e: print("\n", e); sys.exit(1)
    shell_only = [k for k in os.environ if k.startswith("GROQ") and not (env_path.exists() and k in env_path.read_text(encoding="utf-8-sig", errors="replace"))]
    print(f"\nkeys the pool will use: {len(keys)}")
    if shell_only: print("  (also set in your shell environment:", ", ".join(shell_only), ")")
    if "--no-call" in sys.argv: return

    from groq import Groq
    import groq
    for i, k in enumerate(keys, 1):
        tag = f"key#{i}({k[:4]}…{k[-4:]})"
        try:
            raw = Groq(api_key=k, max_retries=0, timeout=30).chat.completions.with_raw_response.create(
                model="openai/gpt-oss-120b", max_completion_tokens=40, messages=[{"role": "user", "content": "Say ok"}])
            h = raw.headers
            print(f"  {tag}: WORKS | per-minute tokens limit={h.get('x-ratelimit-limit-tokens')} remaining={h.get('x-ratelimit-remaining-tokens')}"
                  f" | requests/day limit={h.get('x-ratelimit-limit-requests')} remaining={h.get('x-ratelimit-remaining-requests')}")
        except groq.RateLimitError as e:
            m = re.search(r"try again in ([\dhms.]+)", str(e)); per = "per day" in str(e).lower()
            print(f"  {tag}: valid key, but {'DAILY' if per else 'per-minute'} limit reached; retry in {m.group(1) if m else '?'}")
        except groq.AuthenticationError: print(f"  {tag}: INVALID key (401) - re-copy it from that account's console")
        except Exception as e: print(f"  {tag}: error {type(e).__name__}: {str(e)[:120]}")
    print("\nIMPORTANT: keys from the SAME Groq organization share one quota. Each key must come from a different account/org to add capacity.")

if __name__ == "__main__":
    main()
