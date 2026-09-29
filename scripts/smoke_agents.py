"""Offline smoke for health -> planner -> content -> briefs -> ics -> recap. No keys. Run: uv run python scripts/smoke_agents.py"""
import os, tempfile
from pathlib import Path

os.environ["SECOND_BRAIN_DATA"] = tempfile.mkdtemp()
for k in ("FIREWORKS_API_KEY", "ANTHROPIC_API_KEY", "FLWR_RUNTIME_BASE_URL", "FLWR_RUNTIME_API_KEY"):
    os.environ.pop(k, None)

from second_brain import agent_app, runtime
from second_brain.executor import briefs, base


class Events:
    def emit(self, e): pass


class A:  # stub AgentSession
    events = Events()
    prompt = ""
    class connectors:
        @staticmethod
        def tools(n): raise RuntimeError("no connectors offline")


class Ctx:
    state = {}
    run_config = {}


agent, ctx = A(), Ctx()
h = lambda t: agent_app.handle(agent, ctx, t)

print(h("My goal: land an AI security role by December")[:200])
out = h("I slept 5 hours last night")
print(out)
p = runtime.load_profile()
assert p["health_log"] and p["health_log"][-1]["value"] == 5.0, p["health_log"]
assert "Lighter plan" in out and out.count("[health]") == 1 and "model: " in agent_app._model_line()
assert p["health_log"][-1]["typed"].startswith("I slept")
out = h("plan tomorrow")
print(out)
assert "planner" in out
out = h("recap event: great talk on prompt injection defenses at the AI security meetup. photos: speaker on stage; group dinner selfie; slide about LLM red teaming")
print(out)
assert "content" in out
s = runtime.load_state(ctx, "session")
ids = [c["id"] for c in s["cards"]]
assert ids == sorted(set(ids)), ids
# never a brief for a non-approved card
try:
    briefs.brief_for(s["cards"][0], s["goal"]); raise SystemExit("brief for pending card!")
except briefs.NotApproved:
    pass
assert briefs.issue(s) == [] and not (runtime.data_dir() / "ics").exists()
cal = next(c["id"] for c in s["cards"] if c["agent"] == "planner")
post = next(c["id"] for c in s["cards"] if c["agent"] == "content")
skipped = next(c["id"] for c in s["cards"] if c["agent"] == "health")
out = h(f"approve {cal}, {post}, skip {skipped}")
print(out)
assert out.count("=== ACTION BRIEF ===") == 2 and "STOP before the final" in out and "Secret-keyed providers used: no" in out
files = list((runtime.data_dir() / "ics").glob("*.ics"))
assert len(files) == 1
raw = files[0].read_bytes().decode()
assert raw.startswith("BEGIN:VCALENDAR\r\n") and "DTSTART:" in raw and raw.endswith("END:VCALENDAR\r\n")
assert all(len(l.encode()) <= 75 for l in raw.split("\r\n"))
assert base.run({"text": "x"})["ok"] is False
assert "Recap" in h("recap")

main_dir = os.environ["SECOND_BRAIN_DATA"]
# gap 1: decide without a goal / without pending cards; ids = max+1
def fresh():
    os.environ["SECOND_BRAIN_DATA"] = tempfile.mkdtemp()  # state file fallback would leak sessions
    c = Ctx(); c.state = {}
    return c


c2 = fresh()
g = lambda t: agent_app.handle(agent, c2, t)
assert "goal first" in g("approve 1").lower()
h2 = g("I slept 5h")
assert "Lighter plan" in h2
s2 = runtime.load_state(c2, "session"); assert s2["cards"][0]["id"] == 1
assert "goal first" in g("approve 1").lower()  # still no goal
os.environ["SECOND_BRAIN_DATA"] = main_dir
s = runtime.load_state(ctx, "session")
h("skip all")
assert "no pending cards" in h("approve 1").lower()
assert agent_app._next_id(s) == max(c["id"] for c in s["cards"]) + 1
assert "model: " in h("My goal: land an AI security role by December")

# gap 2: health card approval changes alignment; both numbers in recap
c3 = fresh()
k = lambda t: agent_app.handle(agent, c3, t)
k("My goal: land an AI security role by December")
before = runtime.load_state(c3, "session")["alignment_before"]
k("slept 5h")
s3 = runtime.load_state(c3, "session")
hc = [c for c in s3["cards"] if c["agent"] == "health"]; assert len(hc) == 1
assert hc[0]["item"]["hours"] and "Lighter plan" in hc[0]["item"]["text"]
out = k(f"approve {hc[0]['id']}")
s3 = runtime.load_state(c3, "session")
assert s3["alignment_after"] != before, (before, s3["alignment_after"])
assert f"Alignment: {before} -> {s3['alignment_after']}" in out

# gap 3: post about <event> -> per-community cards -> brief after approval
n0 = len(s3["cards"])
out = k("post about the AI security meetup talk on prompt injection")
s3 = runtime.load_state(c3, "session")
posts = [c for c in s3["cards"] if c["agent"] == "content"]
comms = runtime.load_profile().get("communities", [])[:3] or ["your network"]
assert len(posts) == len(comms) and all(c["item"]["kind"] == "post" for c in posts), posts
assert "prompt injection" in posts[0]["item"]["draft"]
out = k(f"approve {posts[0]['id']}")
assert out.count("=== ACTION BRIEF ===") == 1 and "Copy-ready post text" in out
assert "goal first" in agent_app.handle(agent, fresh(), "recap event X").lower()
print("smoke_agents OK")
