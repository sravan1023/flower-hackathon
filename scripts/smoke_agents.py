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
assert "Lighter day" in out
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
print("smoke_agents OK")
