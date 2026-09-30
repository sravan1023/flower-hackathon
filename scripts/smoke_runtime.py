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
for k in ("FLWR_RUNTIME_BASE_URL", "FLWR_RUNTIME_API_KEY", "FIREWORKS_API_KEY", "ANTHROPIC_API_KEY", "SECOND_BRAIN_LOCAL", "NEBIUS_KIMI_API_KEY", "NEBIUS_MINIMAX_API_KEY"):
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

# router: with Nebius keys and a failing kimi, a set_goal turn still completes (minimax fake answers), LAST_PROVIDER tracked
from second_brain import router  # noqa: E402

_seen = []


def _fake(name, msgs):
    _seen.append(name)
    if name == "kimi":
        raise TimeoutError("timeout")
    raise RuntimeError("down")


os.environ.update(NEBIUS_KIMI_API_KEY="k1", NEBIUS_MINIMAX_API_KEY="k2")
_orig = router._call
router._call = _fake
router._DEAD.clear()
agent_app.DEADLINE_S, agent_app.BEAT_S = 150, 20
assert "Goal" in run("My goal: land an AI security role by December")
assert _seen[:2] == ["kimi", "minimax"] and router.LAST_PROVIDER is None, (_seen[:3], router.LAST_PROVIDER)
assert _seen.count("kimi") == 1, "circuit breaker: kimi tried once"
router._call = _orig
router._DEAD.clear()
for _k in ("NEBIUS_KIMI_API_KEY", "NEBIUS_MINIMAX_API_KEY"):
    os.environ.pop(_k, None)
print("ok router fallthrough + breaker in a full turn")


class _SC:
    def __init__(self, sid, rid=0):
        self.state, self.series_id, self.run_id = {}, sid, rid


import tempfile as _tf

from second_brain import runtime  # noqa: E402

os.environ["SECOND_BRAIN_DATA"] = _tf.mkdtemp()
runtime.save_state(_SC(7, 1), "session", {"u": "A"})
assert runtime.load_state(_SC(7, 2), "session") == {"u": "A"}, "same series continues via file"
assert runtime.load_state(_SC(8, 3), "session") is None, "other series must not see it"
assert runtime.load_state(_SC(0, 4), "session") is None, "series-less run must not see series state"
print("ok state file fallback keyed by series")
print("SMOKE RUNTIME OK")
