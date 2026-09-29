"""Offline runtime smoke: fake AgentSession/Context, all providers/connectors failing or hanging.

Asserts: every emitted event is valid (non-empty str type, JSON-serialisable), an immediate
'working' delta comes first, a final answer delta + exactly one response.completed follow,
even when handle() raises or hangs. Run: uv run python scripts/smoke_runtime.py
"""

import json
import os
import tempfile
import time

os.environ["SECOND_BRAIN_DATA"] = tempfile.mkdtemp()
for k in ("FLWR_RUNTIME_BASE_URL", "FLWR_RUNTIME_API_KEY", "FIREWORKS_API_KEY", "ANTHROPIC_API_KEY", "SECOND_BRAIN_LOCAL"):
    os.environ.pop(k, None)

from second_brain import agent_app


class Events:
    def __init__(self):
        self.got = []

    def emit(self, e):
        assert isinstance(e.get("type"), str) and e["type"], e
        json.dumps(e)
        self.got.append(e)


class Connectors:
    def tools(self, names):
        raise RuntimeError("no connectors")

    def call(self, c):
        time.sleep(999)


class Agent:
    def __init__(self, prompt):
        self.prompt = prompt
        self.events = Events()
        self.connectors = Connectors()


class Ctx:
    run_config = {"agent.model": "x"}
    state = {}


def run(prompt):
    a = Agent(prompt)
    agent_app.main(a, Ctx())
    ev = a.events.got
    types = [e["type"] for e in ev]
    assert types[0] == "response.output_text.delta" and "Working" in ev[0]["delta"], types
    assert types.count("response.completed") == 1 and types[-1] == "response.completed", types
    text = "".join(e["delta"] for e in ev if e["type"] == "response.output_text.delta")
    assert len(text) > 30, text
    final = ev[-1]["response"]["output"][0]["content"][0]["text"]
    assert final.strip(), final
    return text


t = run("My goal: land an AI security role by December")
assert "Goal" in t, t
print("ok all-providers-down set_goal ->", len(t), "chars")

run("hello there")
print("ok other intent")

orig = agent_app.handle
agent_app.handle = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
assert "Something went wrong" in run("x")
print("ok exception path")

agent_app.handle = lambda *a, **k: time.sleep(30)
agent_app.DEADLINE_S, agent_app.BEAT_S = 2, 1
assert "took longer" in run("x")
print("ok timeout path")
agent_app.handle = orig
print("SMOKE RUNTIME OK")
