import re, time, json
from openai import OpenAI

env = {}
for line in open("data/.env", encoding="utf-8"):
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    v = v.strip()
    if v[:1] and v[:1] in "\"'":
        q = v[0]; end = v.find(q, 1); v = v[1:end] if end > 0 else v[1:]
    else:
        v = re.split(r"\s+#", v)[0].strip()
    env[k.strip()] = v

def red(s):
    s = str(s)
    for k, v in env.items():
        if "KEY" in k and v:
            s = s.replace(v, "<redacted>")
    return re.sub(r"[A-Za-z0-9_\-\.]{24,}", "<redacted>", s)[:200]

MSGS = [{"role": "system", "content": "You are a JSON API."},
        {"role": "user", "content": 'Reply with only JSON {"ok":true}'}]
JOINED = "system: You are a JSON API.\n\nuser: " + MSGS[1]["content"]

def run(name, fn):
    t = time.time()
    try:
        r = fn()
        print(f"  {name}: OK {time.time()-t:.1f}s {r}")
    except Exception as e:
        print(f"  {name}: FAIL {time.time()-t:.1f}s {type(e).__name__} {red(e)}")

for p in ("KIMI", "MINIMAX"):
    model, key = env.get(f"NEBIUS_{p}_MODEL"), env.get(f"NEBIUS_{p}_API_KEY")
    print(p, "model=", model, "key=", "set" if key else "unset", "base=", env.get("NEBIUS_BASE_URL"))
    c = OpenAI(base_url=env.get("NEBIUS_BASE_URL"), api_key=key or "x", timeout=60, max_retries=0)
    run("a_list", lambda: repr(c.responses.create(model=model, input=MSGS).output_text[:120]))
    run("b_string", lambda: repr(c.responses.create(model=model, input=JOINED).output_text[:120]))
    def stream():
        types, text = [], ""
        for ev in c.responses.create(model=model, input=MSGS, stream=True):
            if not types or types[-1] != ev.type: types.append(ev.type)
            if ev.type == "response.output_text.delta": text += ev.delta
        return f"events={types} text={text[:120]!r}"
    run("c_stream", stream)
    run("d_chat", lambda: repr(c.chat.completions.create(model=model, messages=MSGS).choices[0].message.content[:120]))
