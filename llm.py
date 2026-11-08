"""Thin Groq wrapper: strict JSON-schema output, validation, retries/backoff, token accounting, optional key pool.
Model ID and every generation setting is explicit and recorded in the run metadata."""
import hashlib, json, os, re, time
from pathlib import Path
from typing import Optional, Tuple, Type
from pydantic import BaseModel, ValidationError
from schemas import strict_schema
from keypool import KeyPool, DailyLimitReached, AllKeysExhausted   # noqa: F401  (re-exported)

DEFAULT_MODEL = "openai/gpt-oss-120b"

def _is_daily_limit(msg: str) -> bool:
    m = msg.lower()
    return "per day" in m or "(tpd)" in m or "(rpd)" in m

def _retry_after_seconds(e, default: float) -> float:
    try:
        h = e.response.headers.get("retry-after")
        if h: return float(h)
    except Exception: pass
    m = re.search(r"try again in (?:(\d+)m)?(?:([\d.]+)s)?", str(e))
    if m and (m.group(1) or m.group(2)):
        return float(m.group(1) or 0) * 60 + float(m.group(2) or 0)
    return default

class GroqExtractor:
    def __init__(self, model=DEFAULT_MODEL, temperature=0.0, reasoning_effort: Optional[str] = "medium",
                 max_completion_tokens=6000, timeout=120.0, max_attempts=5, seed: Optional[int] = 7, cache_dir: Optional[str] = None,
                 api_key: Optional[str] = None, pool: Optional[KeyPool] = None, client_factory=None, tpm_budget=0):
        self.settings = dict(model=model, temperature=temperature, reasoning_effort=reasoning_effort,
                             max_completion_tokens=max_completion_tokens, timeout=timeout, max_attempts=max_attempts, seed=seed)
        self.use_seed = seed is not None
        if pool is None:
            if api_key is None:
                from config import get_groq_key; api_key = get_groq_key()
            pool = KeyPool([api_key], tpm_budget=tpm_budget)
        self.pool = pool
        self.settings["api_keys_in_pool"] = len(pool.keys)
        if client_factory is None:
            from groq import Groq
            client_factory = lambda key: Groq(api_key=key, timeout=timeout, max_retries=0)   # retries are ours
        self._factory, self._clients = client_factory, {}
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir: self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.strict = True                      # flips to False (json_object mode) if the API rejects the schema

    def _client(self, key):
        if key not in self._clients: self._clients[key] = self._factory(key)
        return self._clients[key]

    def _call(self, client, messages, schema_name, schema, max_tokens):
        s = self.settings
        kw = dict(model=s["model"], messages=messages, temperature=s["temperature"], max_completion_tokens=max_tokens)
        if s["reasoning_effort"]: kw["extra_body"] = {"reasoning_effort": s["reasoning_effort"]}
        if self.use_seed: kw["seed"] = s["seed"]             # best-effort determinism; dropped automatically if the API rejects it
        if self.strict:
            kw["response_format"] = {"type": "json_schema", "json_schema": {"name": schema_name, "strict": True, "schema": schema}}
        else:
            kw["response_format"] = {"type": "json_object"}
        return client.chat.completions.create(**kw)

    def extract(self, system: str, user: str, model_cls: Type[BaseModel], name: str) -> Tuple[Optional[BaseModel], dict]:
        import groq
        schema = strict_schema(model_cls)
        meta = {"name": name, "attempts": 0, "prompt_tokens": 0, "completion_tokens": 0, "reasoning_tokens": 0,
                "latency_s": 0.0, "errors": [], "cached": False, "strict_mode": self.strict, "keys": []}
        key = None
        if self.cache_dir:                                   # DEV-ONLY cache of raw model responses (off by default)
            core = {k: self.settings.get(k) for k in ("model", "temperature", "reasoning_effort", "seed")}
            key = hashlib.sha256(json.dumps([core, system, user, name], sort_keys=True).encode()).hexdigest()
            f = self.cache_dir / f"{key}.json"
            if f.exists():
                raw = json.loads(f.read_text()); meta["cached"] = True
                return model_cls.model_validate_json(raw["content"]), meta

        def sys_with_schema(): return system + "\n\nReturn a single JSON object that validates against this JSON Schema:\n" + json.dumps(schema)
        messages = [{"role": "system", "content": system if self.strict else sys_with_schema()}, {"role": "user", "content": user}]
        max_tokens = self.settings["max_completion_tokens"]
        est = int((len(system) + len(user)) / 3.0) + 1500    # rough request size for per-key pacing
        t0 = time.time(); attempt, rl_waits, content = 0, 0, ""
        while attempt < self.settings["max_attempts"]:
            handle = self.pool.acquire(est)                  # AllKeysExhausted (a DailyLimitReached) propagates to the caller
            api_key = handle[0]; used = 0
            attempt += 1; meta["attempts"] = attempt; meta["keys"].append(self.pool.label(api_key))
            try:
                r = self._call(self._client(api_key), messages, f"{name}_schema", schema, max_tokens)
                u = r.usage
                pt, ct = getattr(u, "prompt_tokens", 0) or 0, getattr(u, "completion_tokens", 0) or 0
                used = pt + ct; meta["prompt_tokens"] += pt; meta["completion_tokens"] += ct
                d = getattr(u, "completion_tokens_details", None)
                meta["reasoning_tokens"] += (getattr(d, "reasoning_tokens", 0) or 0) if d else 0
                content = (r.choices[0].message.content or "").strip()
                if not content:                              # reasoning consumed the whole budget
                    meta["errors"].append("empty content (finish=%s)" % r.choices[0].finish_reason)
                    max_tokens = min(max_tokens * 2, 16000); continue
                parsed = model_cls.model_validate_json(content)
                if key: (self.cache_dir / f"{key}.json").write_text(json.dumps({"content": content}))
                meta["latency_s"] = round(time.time() - t0, 2)
                return parsed, meta
            except ValidationError as e:
                meta["errors"].append("validation: " + str(e)[:300])
                messages = messages[:2] + [{"role": "assistant", "content": content},
                    {"role": "user", "content": "That JSON failed validation: " + str(e)[:600] + "\nReturn the corrected JSON object only."}]
            except groq.BadRequestError as e:
                msg = str(e)[:300]; meta["errors"].append("bad_request: " + msg)
                if self.use_seed and "seed" in msg.lower(): self.use_seed = False; continue
                if self.strict and ("schema" in msg.lower() or "response_format" in msg.lower() or "strict" in msg.lower()):
                    self.strict = False; meta["strict_mode"] = False; messages[0]["content"] = sys_with_schema(); continue
                if "json_validate_failed" in msg or "failed to generate" in msg.lower(): continue
                break
            except groq.RateLimitError as e:
                msg = str(e); attempt -= 1                   # rate limits never use up attempts
                if _is_daily_limit(msg):                     # this key is done for now -> another key (or stop)
                    self.pool.mark_daily(api_key, _retry_after_seconds(e, 3600))
                    meta["errors"].append(f"daily_limit {self.pool.label(api_key)}"); continue
                rl_waits += 1
                wait = min(_retry_after_seconds(e, 2 ** min(rl_waits, 5)) + 0.5, 120)
                self.pool.cooldown(api_key, wait); meta["errors"].append(f"rate_limit_minute wait {wait:.0f}s")
                if rl_waits > 40: break
            except (groq.AuthenticationError, groq.PermissionDeniedError) as e:
                self.pool.disable(api_key, "auth error"); meta["errors"].append(f"auth {self.pool.label(api_key)}"); attempt -= 1
            except (groq.APIConnectionError, groq.APITimeoutError, groq.InternalServerError) as e:
                meta["errors"].append(type(e).__name__); time.sleep(min(2 ** attempt, 30))
            except groq.APIStatusError as e:
                meta["errors"].append(f"status {e.status_code}: {str(e)[:200]}")
                if e.status_code in (404,): break
                time.sleep(min(2 ** attempt, 30))
            finally:
                self.pool.release(handle, used)
        meta["latency_s"] = round(time.time() - t0, 2)
        return None, meta
