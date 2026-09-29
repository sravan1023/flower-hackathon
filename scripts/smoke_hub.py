"""Offline hub-discovery + set_goal speed smoke.

Asserts: (1) hub discovery requests ONLY the web_fetch connector, parses events from the fetched page,
drops events whose URL is not in the fetched text; (2) a set_goal turn issues <= 2 LLM calls (router.complete),
run concurrently. Run: uv run python scripts/smoke_hub.py
"""

import json
import os
import tempfile
import threading
import time

os.environ["SECOND_BRAIN_DATA"] = tempfile.mkdtemp()
for k in ("FIREWORKS_API_KEY", "ANTHROPIC_API_KEY", "SECOND_BRAIN_LOCAL", "NEBIUS_KIMI_API_KEY", "NEBIUS_MINIMAX_API_KEY"):
    os.environ.pop(k, None)

from second_brain import agent_app, goal_engine, router, runtime

PAGE = "Upcoming: AI Security Night - Oct 3 - https://lu.ma/ai-sec-night ; Agents Meetup - Oct 5 - https://www.meetup.com/agents/events/1"
requested: list[list[str]] = []
fetch_calls: list[dict] = []


class Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def model_dump(self, exclude_none=True):
        return dict(self.__dict__)


class Responses:
    def __init__(self):
        self.n = 0

    def create(self, **kw):
        self.n += 1
        if kw.get("tools") and self.n == 1:
            return Obj(output=[Obj(type="function_call", name="web_fetch", call_id="c1", arguments=json.dumps({"url": "https://lu.ma/discover"}))], output_text="")
        return Obj(output=[], output_text="events listed")


class Client:
    responses = Responses()


class Connectors:
    def tools(self, names):
        requested.append(list(names))
        return [{"type": "function", "name": "web_fetch"}]

    def call(self, c):
        fetch_calls.append(c)
        return {"type": "function_call_output", "call_id": c["call_id"], "output": json.dumps({"content": PAGE})}


class Agent:
    connectors = Connectors()


llm = {"active": 0, "peak": 0, "total": 0}
lock = threading.Lock()


def fake_complete(task, messages, json_schema=None, default=None):
    with lock:
        llm["active"] += 1
        llm["total"] += 1
        llm["peak"] = max(llm["peak"], llm["active"])
    time.sleep(0.3)
    try:
        if json_schema and "events" in json_schema.get("required", []):
            return {"events": [
                {"title": "AI Security Night", "url": "https://lu.ma/ai-sec-night", "date": "Oct 3", "summary": "x"},
                {"title": "Agents Meetup", "url": "https://www.meetup.com/agents/events/1", "date": "Oct 5", "summary": "y"},
                {"title": "Invented", "url": "https://example.com/made-up", "date": "Oct 9", "summary": "z"},
            ]}
        return default
    finally:
        with lock:
            llm["active"] -= 1


# 0. real router chain with Nebius keys set (fake _call): kimi first, then minimax; health never reaches claude
_orig_call = router._call
_seen: list[str] = []


def _fake_call(name, msgs):
    _seen.append(name)
    if name == "kimi" and _fail["kimi"]:
        raise RuntimeError("429")
    return '{"ok": 1}'


_fail = {"kimi": False}
os.environ.update(NEBIUS_KIMI_API_KEY="k1", NEBIUS_MINIMAX_API_KEY="k2", ANTHROPIC_API_KEY="k4")
router._call = _fake_call
_sch = {"type": "object", "required": ["ok"]}
assert router.complete("plan", [], _sch, default={}) == {"ok": 1} and router.LAST_PROVIDER == "kimi" and _seen == ["kimi"], _seen
_fail["kimi"] = True
router._DEAD.clear()
_seen.clear()
assert router.complete("plan", [], _sch, default={}) == {"ok": 1} and router.LAST_PROVIDER == "minimax" and _seen == ["kimi", "minimax"], _seen
router._DEAD.clear()
_seen.clear()
router.complete("health", [], _sch, default={})
assert "claude" not in _seen and "minimax" not in _seen, _seen
for _k in ("NEBIUS_KIMI_API_KEY", "NEBIUS_MINIMAX_API_KEY", "ANTHROPIC_API_KEY"):
    os.environ.pop(_k, None)
router._DEAD.clear()
router._call = _orig_call
print("ok router chain (kimi -> minimax, health no claude)")

router.available = lambda name: name == "flower"
router._openai = lambda name: Client()
router._model = lambda name: "stub"
router.complete = fake_complete

# 1. hub discovery: only web_fetch, <= 3 fetches, events grounded in fetched text
assert runtime.mode() == "hub", runtime.mode()
evs = goal_engine.discover_events(Agent(), "land an AI security role", {"topics": ["AI security", "agents"], "communities": []})
assert requested and all(r == ["web_fetch"] for r in requested), requested
assert len(fetch_calls) <= 3 and fetch_calls, fetch_calls
urls = [e["url"] for e in evs]
assert urls == ["https://lu.ma/ai-sec-night", "https://www.meetup.com/agents/events/1"], urls
hub = goal_engine.hub_urls("x y", {"topics": ["AI security"]})
assert len(hub) == 3 and all("web_search" not in u for u in hub) and "keywords=AI+security" in hub[2], hub
print("ok discovery:", [e["title"] for e in evs])

# no fetched data -> profile communities fallback
router._openai = lambda name: (_ for _ in ()).throw(RuntimeError("down"))
fb = goal_engine.discover_events(Agent(), "g", {"communities": ["AI Tinkerers"]})
assert fb and fb[0]["title"] == "AI Tinkerers meetup" and fb[0]["url"] == "", fb
print("ok fallback")


# 2. set_goal: <= 2 LLM calls, concurrent
class Ctx:
    run_config = {}
    state = {}


llm.update(active=0, peak=0, total=0)
t0 = time.time()
reply = agent_app.handle(Agent(), Ctx(), "My goal: land an AI security role by December")
dt = time.time() - t0
assert "Goal" in reply and "December" in reply, reply[:200]
assert llm["total"] <= 2, llm
assert llm["peak"] <= 2, llm
print(f"ok set_goal: llm={llm} in {dt:.1f}s")
print("smoke_hub OK")
