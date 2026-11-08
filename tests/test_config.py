import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import pytest, config

def clear(monkeypatch):
    import os
    for k in list(os.environ):
        if k.startswith("GROQ"): monkeypatch.delenv(k)

def test_accepts_both_naming_styles_in_numeric_order(monkeypatch):
    clear(monkeypatch)
    for k, v in {"GROQ_API_KEY": "gsk_p", "GROQ_API_KEY2": "gsk_2", "GROQ_API_KEY_3": "gsk_3", "GROQ_API_KEY10": "gsk_10", "GROQ_API_KEY4": "gsk_4"}.items(): monkeypatch.setenv(k, v)
    assert config.get_groq_keys() == ["gsk_p", "gsk_2", "gsk_3", "gsk_4", "gsk_10"]

def test_dedupes_strips_quotes_and_reads_comma_list(monkeypatch):
    clear(monkeypatch)
    monkeypatch.setenv("GROQ_API_KEY", '"gsk_a"'); monkeypatch.setenv("GROQ_API_KEY2", "gsk_a"); monkeypatch.setenv("GROQ_API_KEYS", "gsk_b, gsk_c ,gsk_a")
    assert config.get_groq_keys() == ["gsk_a", "gsk_b", "gsk_c"]

def test_single_key_helper_ignores_extras(monkeypatch):
    clear(monkeypatch); monkeypatch.setenv("GROQ_API_KEY", "gsk_only"); monkeypatch.setenv("GROQ_API_KEY2", "gsk_x")
    assert config.get_groq_key() == "gsk_only"

def test_no_keys_raises(monkeypatch):
    clear(monkeypatch)
    with pytest.raises(RuntimeError): config.get_groq_keys()
