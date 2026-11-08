"""Central config. Reads GROQ_API_KEY from the environment.

A local .env file is loaded if present, but a real environment variable always
wins (override=False), so the evaluator's one-command run works with either.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

def get_groq_key() -> str:
    key = os.environ.get("GROQ_API_KEY", "").strip().strip('"').strip("'")
    if not key:
        raise RuntimeError(
            "GROQ_API_KEY not found. Put it in a .env file next to this script "
            "(GROQ_API_KEY=gsk_...) or export it in your shell.")
    if not key.startswith("gsk_"):
        print("WARNING: key does not start with 'gsk_' - is this a Groq key (console.groq.com)?")
    return key

def get_groq_keys() -> list:
    """DEV-ONLY: all keys found in the environment / .env. Accepts GROQ_API_KEY, GROQ_API_KEY_2 or GROQ_API_KEY2 (any number),
    and/or a comma-separated GROQ_API_KEYS. Order is preserved (primary first, then by number); duplicates are removed."""
    import re
    found = []
    def add(v):
        v = (v or "").strip().strip('"').strip("'")
        if v and v not in found: found.append(v)
    add(os.environ.get("GROQ_API_KEY"))
    numbered = []
    for name in os.environ:
        m = re.fullmatch(r"GROQ_API_KEY_?(\d+)", name)
        if m: numbered.append((int(m.group(1)), name))
    for _, name in sorted(numbered): add(os.environ[name])
    for v in os.environ.get("GROQ_API_KEYS", "").split(","): add(v)
    if not found:
        raise RuntimeError("No GROQ_API_KEY* found. Put GROQ_API_KEY=gsk_... (and optionally GROQ_API_KEY_2, GROQ_API_KEY_3 ...) in .env")
    return found
