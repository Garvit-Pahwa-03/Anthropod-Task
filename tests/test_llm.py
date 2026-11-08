import sys, pathlib, json, types
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import httpx, groq, pytest
from llm import GroqExtractor
from keypool import KeyPool, AllKeysExhausted
from schemas import EventsExtraction
import llm as llm_mod

def err(cls, status, msg):
    req = httpx.Request("POST", "https://api.groq.com/x"); resp = httpx.Response(status, request=req, headers={"retry-after": "0"})
    return cls(msg, response=resp, body={"error": {"message": msg}})

def resp(content, finish="stop"):
    u = types.SimpleNamespace(prompt_tokens=100, completion_tokens=50, completion_tokens_details=types.SimpleNamespace(reasoning_tokens=30))
    return types.SimpleNamespace(usage=u, choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=content), finish_reason=finish)])

class FakeClient:
    def __init__(self, script):
        self.script, self.calls = list(script), []
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self._create))
    def _create(self, **kw):
        self.calls.append(kw); x = self.script.pop(0)
        if isinstance(x, Exception): raise x
        return x

GOOD = json.dumps({"events": []})
class Clock:
    def __init__(self): self.t = 1000.0
    def now(self): return self.t
    def sleep(self, s): self.t += s
def mk(script, **kw):
    llm_mod.time.sleep = lambda s: None                      # no real sleeping in tests
    clk = Clock(); fake = FakeClient(script)
    pool = KeyPool(["gsk_test_key_1234"], clock=clk.now, sleep=clk.sleep)
    ex = GroqExtractor(pool=pool, client_factory=lambda k: fake, **kw)
    ex.client = fake                                         # tests inspect ex.client.calls
    return ex

def test_happy_path_and_token_accounting():
    ex = mk([resp(GOOD)]); parsed, meta = ex.extract("sys", "usr", EventsExtraction, "events")
    assert parsed.events == [] and meta["prompt_tokens"] == 100 and meta["reasoning_tokens"] == 30
    kw = ex.client.calls[0]
    assert kw["temperature"] == 0.0 and kw["response_format"]["json_schema"]["strict"] is True and kw["extra_body"] == {"reasoning_effort": "medium"}

def test_schema_rejected_falls_back_to_json_object_mode():
    ex = mk([err(groq.BadRequestError, 400, "invalid response_format json_schema strict not supported"), resp(GOOD)])
    parsed, meta = ex.extract("sys", "usr", EventsExtraction, "events")
    assert parsed is not None and ex.strict is False and ex.client.calls[1]["response_format"] == {"type": "json_object"}
    assert "JSON Schema" in ex.client.calls[1]["messages"][0]["content"]

def test_empty_content_retries_with_bigger_budget():
    ex = mk([resp("", finish="length"), resp(GOOD)], max_completion_tokens=1000)
    parsed, meta = ex.extract("s", "u", EventsExtraction, "events")
    assert parsed is not None and ex.client.calls[1]["max_completion_tokens"] == 2000

def test_validation_error_triggers_repair_turn():
    ex = mk([resp('{"events": "nope"}'), resp(GOOD)])
    parsed, meta = ex.extract("s", "u", EventsExtraction, "events")
    assert parsed is not None and ex.client.calls[1]["messages"][-1]["content"].startswith("That JSON failed validation")

def test_rate_limit_then_success():
    ex = mk([err(groq.RateLimitError, 429, "slow down"), resp(GOOD)])
    parsed, meta = ex.extract("s", "u", EventsExtraction, "events")
    assert parsed is not None and any("rate_limit" in e for e in meta["errors"])

def test_connection_error_then_success():
    ex = mk([groq.APIConnectionError(request=httpx.Request("POST", "https://x")), resp(GOOD)])
    assert ex.extract("s", "u", EventsExtraction, "events")[0] is not None

def test_gives_up_cleanly_after_max_attempts():
    ex = mk([groq.APIConnectionError(request=httpx.Request("POST", "https://x"))] * 3, max_attempts=3)
    parsed, meta = ex.extract("s", "u", EventsExtraction, "events")
    assert parsed is None and meta["attempts"] == 3

def test_auth_error_disables_key_and_stops():
    ex = mk([err(groq.AuthenticationError, 401, "bad key"), resp(GOOD)])
    with pytest.raises(AllKeysExhausted) as ei: ex.extract("s", "u", EventsExtraction, "events")
    assert "disabled" in str(ei.value) and len(ex.client.calls) == 1

def test_cache_roundtrip(tmp_path):
    ex = mk([resp(GOOD)], cache_dir=str(tmp_path)); ex.extract("s", "u", EventsExtraction, "events")
    ex2 = mk([], cache_dir=str(tmp_path)); parsed, meta = ex2.extract("s", "u", EventsExtraction, "events")
    assert parsed is not None and meta["cached"] is True


DAILY = ("Rate limit reached for model `openai/gpt-oss-120b` in organization `org_x` service tier `on_demand` on tokens per day (TPD): "
         "Limit 200000, Used 199100, Requested 5200. Please try again in 12m3s.")
MINUTE = ("Rate limit reached for model `openai/gpt-oss-120b` on tokens per minute (TPM): Limit 8000, Used 6200, Requested 5100. "
          "Please try again in 4.5s.")

def test_daily_limit_on_only_key_raises_and_is_not_retried():
    ex = mk([err(groq.RateLimitError, 429, DAILY), resp(GOOD)])
    with pytest.raises(llm_mod.DailyLimitReached): ex.extract("s", "u", EventsExtraction, "events")
    assert len(ex.client.calls) == 1

def test_minute_limit_waits_do_not_consume_attempts():
    ex = mk([err(groq.RateLimitError, 429, MINUTE)] * 6 + [resp(GOOD)], max_attempts=3)
    parsed, meta = ex.extract("s", "u", EventsExtraction, "events")
    assert parsed is not None and meta["attempts"] == 1

def test_retry_after_parsed_from_message():
    e = err(groq.RateLimitError, 429, MINUTE); e.response.headers.pop("retry-after")
    assert llm_mod._retry_after_seconds(e, 99) == 4.5
    assert llm_mod._is_daily_limit(DAILY) and not llm_mod._is_daily_limit(MINUTE)

def test_cache_key_does_not_depend_on_pool_size_or_timeouts(tmp_path):
    ex = mk([resp(GOOD)], cache_dir=str(tmp_path)); ex.extract("s", "u", EventsExtraction, "events")
    ex2 = mk([], cache_dir=str(tmp_path), timeout=999.0, max_attempts=2)          # different non-semantic settings
    ex2.pool.keys.append("gsk_second_key_5678"); ex2.settings["api_keys_in_pool"] = 5
    parsed, meta = ex2.extract("s", "u", EventsExtraction, "events")
    assert meta["cached"] is True

def test_seed_is_sent_and_dropped_if_api_rejects_it():
    ex = mk([err(groq.BadRequestError, 400, "unknown parameter: seed"), resp(GOOD)])
    parsed, meta = ex.extract("s", "u", EventsExtraction, "events")
    assert parsed is not None and ex.client.calls[0]["seed"] == 7 and "seed" not in ex.client.calls[1]

def test_cache_is_not_shared_between_different_prompts(tmp_path):
    ex = mk([resp(GOOD), resp(GOOD)], cache_dir=str(tmp_path))
    ex.extract("PROMPT-A", "u", EventsExtraction, "events")
    parsed, meta = ex.extract("PROMPT-B", "u", EventsExtraction, "events")
    assert meta["cached"] is False
