import sys
from groq import Groq
from config import get_groq_key

client = Groq(api_key=get_groq_key())

ids = sorted(m.id for m in client.models.list().data)
print("Models visible to your key:")
for i in ids:
    print("  ", i)

MODEL = sys.argv[1] if len(sys.argv) > 1 else "openai/gpt-oss-120b"
if MODEL not in ids:
    sys.exit(f"\n{MODEL} is not available to your key. Re-run with one from the list above, "
             f"e.g. python check_groq.py llama-3.3-70b-versatile")

r = client.chat.completions.create(
    model=MODEL, temperature=0, max_tokens=200,
    messages=[{"role": "user", "content": 'Reply with JSON only: {"ok": true}'}],
    response_format={"type": "json_object"})
print("\n", MODEL, "->", r.choices[0].message.content, "| usage:", r.usage)