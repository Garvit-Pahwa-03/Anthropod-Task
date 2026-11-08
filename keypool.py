"""Pool of Groq API keys (several accounts; permitted by the hiring team). Spreads calls over keys, paces each key's tokens-per-minute,
retires a key for the rest of its quota window when it reports a DAILY limit, and persists that state so a restart
does not waste calls on exhausted keys. With a single key it behaves as a plain one-key client.
"""
import hashlib, json, threading, time
from collections import deque
from pathlib import Path
from typing import List, Optional

class DailyLimitReached(RuntimeError):
    """Groq's per-day quota is exhausted. Retrying cannot help."""

class AllKeysExhausted(DailyLimitReached):
    """Every key is exhausted or disabled."""

def mask(key: str) -> str: return key[:4] + "…" + key[-4:] if len(key) > 10 else "key"
def fingerprint(key: str) -> str: return hashlib.sha256(key.encode()).hexdigest()[:10]

class KeyPool:
    def __init__(self, keys: List[str], tpm_budget: int = 0, ledger_path: Optional[str] = None,
                 clock=time.time, sleep=time.sleep):
        seen, self.keys = set(), []
        for k in keys:
            k = k.strip()
            if k and k not in seen: seen.add(k); self.keys.append(k)
        if not self.keys: raise ValueError("no API keys supplied")
        self.tpm_budget, self.clock, self.sleep = tpm_budget, clock, sleep
        self.lock = threading.Lock()
        self.ledger_path = Path(ledger_path) if ledger_path else None
        self.state = {k: dict(window=deque(), exhausted_until=0.0, cooldown_until=0.0, disabled="", tokens=0,
                              calls=0, daily_hits=0, minute_hits=0) for k in self.keys}
        self._load_ledger()

    # ---- identification -----------------------------------------------------------------------
    def label(self, key: str) -> str: return f"key#{self.keys.index(key) + 1}({mask(key)})"

    # ---- persistence ---------------------------------------------------------------------------
    def _load_ledger(self):
        if not self.ledger_path or not self.ledger_path.exists(): return
        try: data = json.loads(self.ledger_path.read_text())
        except Exception: return
        now = self.clock()
        for k in self.keys:
            e = data.get(fingerprint(k), {}).get("exhausted_until", 0)
            if e > now: self.state[k]["exhausted_until"] = e

    def _save_ledger(self):
        if not self.ledger_path: return
        data = {fingerprint(k): {"exhausted_until": st["exhausted_until"], "tokens_this_session": st["tokens"]}
                for k, st in self.state.items()}
        self.ledger_path.write_text(json.dumps(data, indent=1))

    # ---- core API ---------------------------------------------------------------------------------
    def acquire(self, est_tokens: int):
        """Block until some key has capacity; returns a handle (key, entry). Raises AllKeysExhausted if none can ever serve."""
        while True:
            with self.lock:
                now = self.clock()
                live = [k for k in self.keys if not self.state[k]["disabled"] and self.state[k]["exhausted_until"] <= now]
                if not live: raise AllKeysExhausted(self.exhausted_message(now))
                ready, waits = [], []
                for k in live:
                    st = self.state[k]
                    while st["window"] and now - st["window"][0][0] >= 60: st["window"].popleft()
                    if st["cooldown_until"] > now: waits.append(st["cooldown_until"] - now); continue
                    load = sum(e[1] for e in st["window"])
                    if self.tpm_budget and load > 0 and load + est_tokens > self.tpm_budget:
                        waits.append(st["window"][0][0] + 60 - now); continue
                    ready.append((load, self.keys.index(k), k))
                if ready:
                    _, _, k = min(ready)
                    entry = [now, est_tokens]; self.state[k]["window"].append(entry); self.state[k]["calls"] += 1
                    return (k, entry)
                wait = max(0.2, min(waits)) if waits else 0.5
            self.sleep(min(wait, 5.0))

    def release(self, handle, actual_tokens: int):
        k, entry = handle
        with self.lock:
            entry[1] = actual_tokens; self.state[k]["tokens"] += actual_tokens

    def mark_daily(self, key: str, retry_after_s: float):
        with self.lock:
            st = self.state[key]; st["exhausted_until"] = self.clock() + max(retry_after_s, 60.0); st["daily_hits"] += 1
            self._save_ledger()

    def cooldown(self, key: str, wait_s: float):
        with self.lock:
            st = self.state[key]; st["cooldown_until"] = self.clock() + wait_s; st["minute_hits"] += 1

    def disable(self, key: str, reason: str):
        with self.lock: self.state[key]["disabled"] = reason

    # ---- reporting --------------------------------------------------------------------------------
    def exhausted_message(self, now=None) -> str:
        now = self.clock() if now is None else now
        parts = []
        for k in self.keys:
            st = self.state[k]
            if st["disabled"]: parts.append(f"{self.label(k)}: disabled ({st['disabled']})")
            else: parts.append(f"{self.label(k)}: daily limit, resets in ~{max(0, st['exhausted_until'] - now) / 60:.0f} min")
        return "No usable Groq key left. " + "; ".join(parts)

    def summary(self) -> list:
        now = self.clock()
        return [{"key": self.label(k), "calls": st["calls"], "tokens": st["tokens"], "daily_limit_hits": st["daily_hits"],
                 "minute_limit_hits": st["minute_hits"], "disabled": st["disabled"],
                 "exhausted_for_min": round(max(0, st["exhausted_until"] - now) / 60, 1)} for k, st in self.state.items()]