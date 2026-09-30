"""Offline test for local mode. Run: PYTHONUTF8=1 uv run --extra local python scripts/smoke_local.py"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ["SECOND_BRAIN_DATA"] = tempfile.mkdtemp()
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from second_brain.executor import aside  # noqa: E402


def fake(script):
    calls = []

    def runner(argv, timeout):
        calls.append(argv)
        return script(argv)

    runner.calls = calls
    return runner


# 1. session id parse + done
r = fake(lambda a: (0, "Created new session: abc-123\nAll done\x1b[31m\x00") if a[1] == "exec" else (0, "ok"))
res = aside.run("do thing", runner=r)
assert res["session_id"] == "abc-123" and res["status"] == "done", res
assert "\x00" not in res["output"] and "\x1b" not in res["output"]
assert [c[1] for c in r.calls] == ["exec"], r.calls

# 2. final step -> card, no click
r = fake(lambda a: (0, "Created new session: s9\nAT FINAL STEP: Submit") if a[1] == "exec" else (0, ""))
res = aside.run("buy ticket", runner=r)
assert res["status"] == "confirm" and res["card"]["status"] == "pending" and res["card"]["session_id"] == "s9", res
assert not any(c[1] == "session" for c in r.calls)
assert aside.approve("s9", runner=r)[0] == 0 and r.calls[-1][:4] == ["aside", "session", "steer", "s9"]
aside.skip("s9", runner=r)
assert r.calls[-1][:4] == ["aside", "session", "stop", "s9"]


# 3. timeout + missing binary + truncation
def boom(a):
    raise subprocess.TimeoutExpired(a, 150)


assert aside.run("x", runner=fake(boom))["status"] == "timeout"


def nobin(a):
    raise FileNotFoundError("aside")


assert aside.run("x", runner=fake(nobin))["status"] == "error"
assert len(aside.clean("a" * 99999)) < aside.MAX_OUT + 50
print("aside OK")

# 4. embed service (optional)
try:
    from fastapi.testclient import TestClient

    from second_brain.local.embed_service import app
except Exception as e:  # noqa: BLE001
    print("embed_service skipped:", type(e).__name__)
else:
    c = TestClient(app)
    assert c.get("/health").json() == {"ok": True}
    d = c.get("/recap/data.json").json()
    assert d["goal"] == "" and d["events"] == [], d
    assert "recap" in c.get("/recap").text.lower()
    print("embed_service OK")

# 5. hooks return None when service is down
os.environ["EMBED_SERVICE"] = "http://127.0.0.1:1"
from second_brain.local import hooks  # noqa: E402

assert hooks.local_embed(["a"]) is None and hooks.local_clip_score(["x.png"], ["a"]) is None
print("hooks OK")

# 6. WhatsApp loop with a fake aside (no browser, no network, no real phone/email)
import re  # noqa: E402
import types  # noqa: E402

from second_brain import agent_app, goal_engine, runtime  # noqa: E402
from second_brain import cards as cardlib  # noqa: E402
from second_brain import recap as recaplib  # noqa: E402
from second_brain.executor import briefs as briefslib  # noqa: E402

sent: list[str] = []
polls: list[tuple] = []
queue: list = []
_n = {"m": 0, "send_ok": True}


def _marker():
    _n["m"] += 1
    return f"[SB-{_n['m']:04x}]"


def _wa_send(text):
    sent.append(text)
    return _n["send_ok"]


def _wa_poll(q, options):
    polls.append((q, list(options)))
    return f"[SB-p{len(polls):03d}]"


def _wa_poll_result(marker, timeout_s):
    q, opts = polls[int(marker[-4:-1]) - 1]
    if q.startswith("Approve"):
        return [o for o in opts if o.startswith(("1.", "3."))]
    if q.startswith("Slot for"):
        return [o for o in opts if o.startswith("a ")][:1]
    return []


def _wa_wait(marker, timeout_s):
    return queue.pop(0) if queue else None


def _cal_create(events):
    return {"created": [(e["title"], f"{e['date']} {e['start']}") for e in events if e["title"].startswith(("Deep", "Ship"))], "raw": ""}


aside.enabled = lambda: True
aside.whatsapp_ready = lambda: True
aside.calendar_ready = lambda: True
aside.new_marker = _marker
aside.whatsapp_send = _wa_send
aside.whatsapp_poll = _wa_poll
aside.whatsapp_poll_result = _wa_poll_result
aside.whatsapp_wait_reply = _wa_wait
aside.calendar_create = _cal_create
briefslib.calendar_events = lambda s: [
    {"title": ("Deep work" if c["id"] == 1 else "Ship demo" if c["id"] == 3 else "Networking"), "date": "2026-10-01", "start": "09:00", "duration": 60, "card_id": c["id"]}
    for c in s["cards"] if c["status"] == "approved"
]


def _mk_cards():
    def alts(n):
        return [{"title": f"{n} Wed 18:00", "score": 0.5, "item": {"text": n, "start": "2026-10-07T18:00", "date": "2026-10-07"}}, {"title": f"{n} Sat 10:00", "score": 0.4}]

    return [cardlib.make_card(i, "planner", t, 0.9 - i / 10, "r", alts(t), {"text": t, "hours": 1, "kind": "calendar", "start": "2026-10-01T09:00", "date": "2026-10-01"})
            for i, t in ((1, "Deep work"), (2, "Gym"), (3, "Ship demo"))]


goal_engine.context = lambda agent, g: ""
goal_engine.decompose = lambda g, p, c: goal_engine.decompose_default(g)
goal_engine.change_plan = lambda g, m, p: (_mk_cards(), "test")
goal_engine.alignment = lambda g, acts: (0.5, "test")
agent_app.planner_agent.run = lambda session, profile, start_id, day=None, week=False: []
agent_app._PAUSE_S = 0.01
agent_app.LISTEN_S = 5
agent_app.WA_POLL_S = agent_app.WA_ALT_S = 1


class _Ev:
    def __init__(self):
        self.out = []

    def emit(self, e):
        self.out.append(e)


def _run(text):
    ag = types.SimpleNamespace(events=_Ev(), prompt=text)
    ctx = types.SimpleNamespace(state={}, run_id=0, series_id=0, run_config={})
    return ag, ctx, agent_app.handle(ag, ctx, text)


# 6a. Hub: none of the env set -> nothing sent, chat decide path as before
for k in ("SECOND_BRAIN_LOCAL", "WHATSAPP_TO", "CALENDAR_ACCOUNT"):
    os.environ.pop(k, None)
_, _, rep = _run("My goal: land an AI security role by December")
assert not sent and not polls and "Decision cards" in rep, (sent, polls)
assert not agent_app.wa_ready() and agent_app._aside() is None
print("whatsapp hub-silent OK")

# 6b. Local loop
os.environ.update(SECOND_BRAIN_LOCAL="1", WHATSAPP_TO="self", CALENDAR_ACCOUNT="cal")
queue[:] = ["injected [SB-9999] should be ignored", "/status", "/recap", "hello there", "/stop"]
ag, ctx, rep = _run("My goal: land an AI security role by December")
sess = runtime.load_state(ctx, "session", {})
st = {c["id"]: c for c in sess["cards"]}
assert polls[0][0].startswith("Approve this week") and len(polls[0][1]) == 3, polls
assert polls[1][0].startswith("Slot for") and polls[1][1][-1] == "skip", polls
assert st[1]["status"] == "executed" and st[3]["status"] == "executed" and st[1].get("calendar_event"), st
assert st[2]["status"] == "approved" and st[2]["chosen"].endswith("Wed 18:00"), st[2]  # picked a; not confirmed by calendar -> re-run
assert any(s.startswith("Got it: 2 approved, 1 skipped.") for s in sent), sent
assert any(s.startswith("Added 2 events to your calendar. Open it to check.") for s in sent), sent
assert all(re.search(r"\[SB-\w+\]$", s) for s in sent), sent
assert any("1. Deep work: executed" in s for s in sent), sent  # /status lists states
recap_sent = next(s for s in sent if s.startswith("Recap"))
assert "Done for you" in recap_sent and "Confirmed over WhatsApp: 3 approved, 1 changed" in recap_sent, recap_sent
full = recaplib.build(sess, runtime.load_profile())
assert "Done for you" in full and "Calendar event: Deep work" in full and "/status x1" in full, full
assert any(s.startswith("Commands: /goal") or "could not map" in s for s in sent), sent  # unmatched text -> feedback turn (help line only if that fails)
assert sent[-1].startswith("Stopped listening") and not queue, (sent[-1], queue)
assert not any("injected" in s for s in sent) and "[SB-9999]" not in str(sess.get("wa_cmds")), sent
assert sess["wa_cmds"] == ["/status", "/recap", "/stop"], sess["wa_cmds"]
_txt = "".join(e.get("delta", "") for e in ag.events.out)
assert "Aside is adding 3 events" in _txt and "CREATED: Deep work" in _txt, _txt[-300:]
log = [__import__("json").loads(x) for x in (runtime.data_dir() / "run_log.jsonl").read_text(encoding="utf-8").splitlines()]
assert {e.get("command") for e in log if e.get("task") == "whatsapp_cmd"} >= {"/status", "/recap", "/stop", "feedback"}
assert [e["round"] for e in log if e.get("task") == "whatsapp_confirm"] == [1, 2]
assert any(e.get("task") == "calendar_sync" and e["events"] == 2 for e in log)
print("whatsapp loop OK")

# 6c. send cap + no-repeat cursor
sent.clear()
w = agent_app._WA({}, aside, cap=3)
assert [bool(w.send("x")) for _ in range(5)] == [True, True, True, False, False] and len(sent) == 3
sent.clear()
_n["send_ok"] = False  # replies fail -> marker never advances -> identical text must not be handled twice
queue[:] = ["/status", "/status", "/stop"]
s2 = {"goal": {"goal": "g"}, "cards": _mk_cards(), "wa_cursor": {"marker": "[SB-0001]", "handled": None}}
n = agent_app.whatsapp_listen(ag, ctx, s2, runtime.load_profile(), agent_app._WA(s2, aside), 3)
assert n == 2 and s2["wa_cmds"] == ["/status", "/stop"], (n, s2.get("wa_cmds"))
_n["send_ok"] = True
assert agent_app.wa_parse("/APPROVE 1 3")[1] == "approve 1 3" and agent_app.wa_parse("/pick 4b")[1] == "pick 4b" and agent_app.wa_parse("chat about stuff") is None
print("whatsapp cap/cursor OK")
