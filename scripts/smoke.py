"""Offline smoke test: no keys, no runtime. Run: uv run python scripts/smoke.py"""
import os, tempfile
os.environ["SECOND_BRAIN_DATA"] = tempfile.mkdtemp()
from second_brain import cards as C, goal_engine as G, runtime

class A:  # agent stub with no connectors
    class connectors:
        @staticmethod
        def tools(n): raise RuntimeError("no connectors offline")

p = runtime.load_profile()
goal = G.capture("My goal: land an AI security role by December")
print(goal)
m = G.decompose(goal, p)
cards, be = G.change_plan(goal, m, p)
print(C.render(cards), "\nscorer:", be)
before, _ = G.alignment(goal["goal"], p["activities"])
C.apply(cards, C.parse_reply("approve 1, 3, pick 2b, skip 4"), p)
after, _ = G.alignment(goal["goal"], p["activities"] + [c["item"] for c in cards if c["status"] == "approved"])
print("alignment", before, "->", after, [c["status"] for c in cards], p["preferences"])
assert C.parse_reply("approve 1, 3, pick 2b, skip 4") == {"approve": [1, 3], "skip": [4], "edit": [], "pick": {2: "b"}}
