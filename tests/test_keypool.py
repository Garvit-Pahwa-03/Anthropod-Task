import sys, pathlib, json, types
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import httpx, groq, pytest
from keypool import KeyPool, AllKeysExhausted, DailyLimitReached
from llm import GroqExtractor
from schemas import EventsExtraction

class Clock:
    def __init__(self): self.t = 1000.0
    def now(self): return self.t
    def sleep(self, s): self.t += s

KEYS = ["gsk_aaaaaaaaaa1111", "gsk_bbbbbbbbbb2222", "gsk_cccccccccc3333"]
GOOD = json.dumps({"events": []})
DAILY = "Rate limit reached ... on tokens per day (TPD): Limit 200000, Used 199977, Requested 5231. Please try again in 37m29.856s."

def mkerr(cls, status, msg):
    req = httpx.Request("POST", "https://api.groq.com/x"); resp = httpx.Response(status, request=req)
    return cls(msg, response=resp, body={"error": {"message": msg}})
def ok(tokens=100):
    u = types.SimpleNamespace(prompt_tokens=tokens, completion_tokens=0, completion_tokens_details=None)
    return types.SimpleNamespace(usage=u, choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=GOOD), finish_reason="stop")])

class FakeKeyClient:                                         # behaviour scripted per API key
    def __init__(self, key, behaviour, log):
        self.key, self.behaviour, self.log = key, behaviour, log
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self._create))
    def _create(self, **kw):
        self.log.append(self.key); b = self.behaviour[self.key]
        r = b.pop(0) if len(b) > 1 else b[0]
        if isinstance(r, Exception): raise r
        return r

def build(behaviour, tpm=0, ledger=None):
    clk, log = Clock(), []
    pool = KeyPool(KEYS[:len(behaviour)] if False else list(behaviour), tpm_budget=tpm, clock=clk.now, sleep=clk.sleep, ledger_path=ledger)
    ex = GroqExtractor(pool=pool, client_factory=lambda k: FakeKeyClient(k, behaviour, log))
    return ex, pool, clk, log

# ---- pool mechanics -----------------------------------------------------------------------------------------
def test_acquire_spreads_over_keys():
    clk = Clock(); pool = KeyPool(KEYS, clock=clk.now, sleep=clk.sleep)
    hs = [pool.acquire(1000) for _ in range(3)]
    assert {h[0] for h in hs} == set(KEYS)

def test_per_key_tpm_pacing_waits_for_window():
    clk = Clock(); pool = KeyPool(KEYS[:1], tpm_budget=7000, clock=clk.now, sleep=clk.sleep)
    h1 = pool.acquire(5000); t0 = clk.now()
    h2 = pool.acquire(5000)                                  # would exceed 7000 in the same minute -> must wait ~60s
    assert clk.now() - t0 >= 55

def test_oversized_request_still_allowed_when_window_empty():
    clk = Clock(); pool = KeyPool(KEYS[:1], tpm_budget=7000, clock=clk.now, sleep=clk.sleep)
    assert pool.acquire(9000)[0] == KEYS[0]                  # no deadlock

def test_duplicate_keys_are_deduped():
    assert len(KeyPool([KEYS[0], KEYS[0], " " + KEYS[0]]).keys) == 1

def test_ledger_persists_exhaustion_across_restarts(tmp_path):
    led = str(tmp_path / "ledger.json"); clk = Clock()
    p1 = KeyPool(KEYS[:2], clock=clk.now, sleep=clk.sleep, ledger_path=led); p1.mark_daily(KEYS[0], 2249)
    p2 = KeyPool(KEYS[:2], clock=clk.now, sleep=clk.sleep, ledger_path=led)
    assert all(p2.acquire(100)[0] == KEYS[1] for _ in range(3))
    clk.t += 2300                                            # reset time passes
    p3 = KeyPool(KEYS[:2], clock=clk.now, sleep=clk.sleep, ledger_path=led)
    assert {p3.acquire(100)[0] for _ in range(2)} == set(KEYS[:2])

# ---- rotation through the extractor -----------------------------------------------------------------------------
def test_rotates_to_next_key_when_one_hits_daily_limit():
    beh = {KEYS[0]: [mkerr(groq.RateLimitError, 429, DAILY)], KEYS[1]: [ok()], KEYS[2]: [ok()]}
    ex, pool, clk, log = build(beh)
    parsed, meta = ex.extract("s", "u", EventsExtraction, "events")
    assert parsed is not None and log[0] == KEYS[0] and log[1] in (KEYS[1], KEYS[2])
    assert any("daily_limit" in e for e in meta["errors"])
    # the exhausted key is not used again
    for _ in range(4): ex.extract("s", "u" + str(_), EventsExtraction, "events")
    assert log.count(KEYS[0]) == 1

def test_all_keys_exhausted_raises_with_per_key_report():
    beh = {k: [mkerr(groq.RateLimitError, 429, DAILY)] for k in KEYS}
    ex, pool, clk, log = build(beh)
    with pytest.raises(AllKeysExhausted) as ei: ex.extract("s", "u", EventsExtraction, "events")
    msg = str(ei.value); assert "key#1" in msg and "key#3" in msg and "resets in" in msg
    assert isinstance(ei.value, DailyLimitReached) and len(log) == 3

def test_minute_limit_moves_to_other_key_without_waiting():
    MIN = "Rate limit reached on tokens per minute (TPM): Limit 8000. Please try again in 20s."
    beh = {KEYS[0]: [mkerr(groq.RateLimitError, 429, MIN)], KEYS[1]: [ok()]}
    ex, pool, clk, log = build(beh); t0 = clk.now()
    parsed, meta = ex.extract("s", "u", EventsExtraction, "events")
    assert parsed is not None and log == [KEYS[0], KEYS[1]] and clk.now() - t0 < 5

def test_bad_key_is_disabled_and_run_continues_on_others():
    beh = {KEYS[0]: [mkerr(groq.AuthenticationError, 401, "invalid api key")], KEYS[1]: [ok()]}
    ex, pool, clk, log = build(beh)
    parsed, _ = ex.extract("s", "u", EventsExtraction, "events")
    assert parsed is not None and pool.state[KEYS[0]]["disabled"] == "auth error"

def test_token_accounting_per_key():
    beh = {KEYS[0]: [ok(400)], KEYS[1]: [ok(600)]}
    ex, pool, clk, log = build(beh)
    for i in range(2): ex.extract("s", f"u{i}", EventsExtraction, "events")
    assert sum(s["tokens"] for s in pool.summary()) == 1000

# ---- end-to-end: run.py with --use-key-pool, partial output + resume ------------------------------------------------
def test_run_partial_then_resume(tmp_path, monkeypatch):
    import run, keypool, config
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from test_policy import StubExtractor, booked, EventsExtraction as EE
    calls = {"n": 0, "limit": 6}
    class S(StubExtractor):
        def __init__(self, **kw): self.settings = {}; self.strict = True; self.pool = kw["pool"]
        def extract(self, system, user, cls, name):
            calls["n"] += 1
            if calls["n"] > calls["limit"]: raise AllKeysExhausted("No usable Groq key left. key#1: daily limit, resets in ~30 min")
            return super().extract(system, user, cls, name)
    monkeypatch.setattr(run, "GroqExtractor", S)
    monkeypatch.setattr(config, "get_groq_keys", lambda: KEYS[:2])
    monkeypatch.chdir(pathlib.Path(__file__).resolve().parent.parent)
    out = str(tmp_path / "preds.jsonl")
    argv = ["run.py", "--input", "data/inputs.jsonl", "--output", out, "--limit", "8", "--workers", "1", "--use-key-pool"]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as e1: run.main()
    assert e1.value.code == 2 and len(open(out).read().splitlines()) == 3          # 6 calls = 3 records, then exhausted
    calls["limit"] = 10**6
    monkeypatch.setattr(sys, "argv", argv + ["--resume"])
    run.main()
    lines = [json.loads(l) for l in open(out)]
    assert len(lines) == 8 and len({l["transcript_id"] for l in lines}) == 8 and calls["n"] == 7 + 10   # 3 skipped, 5 new records x2 calls
    assert all(set(l) == {"transcript_id", "disposition", "sub_disposition", "lead_quality", "next_call_at"} for l in lines)
