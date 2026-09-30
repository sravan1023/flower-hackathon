"""Offline smoke for the `demo` flow (five Aside tasks) with a fake aside module.

Run: uv run python scripts/smoke_demo_flow.py
"""

import os
import tempfile
import types

os.environ["SECOND_BRAIN_DATA"] = tempfile.mkdtemp()
for k in ("FIREWORKS_API_KEY", "ANTHROPIC_API_KEY", "NEBIUS_KIMI_API_KEY", "NEBIUS_MINIMAX_API_KEY", "SECOND_BRAIN_LOCAL", "WHATSAPP_TO", "CALENDAR_ACCOUNT"):
    os.environ.pop(k, None)

from second_brain import agent_app, goal_engine, recap as recaplib, router, runtime  # noqa: E402
from second_brain import cards as cardlib  # noqa: E402

calls: list[str] = []
script: dict = {"votes": [], "reply": [], "day": "I went to a security meetup and met two founders."}


def _task(text, timeout=300, runner=None):
    calls.append(text)
    if "Create a poll" in text:
        return "noise\nRESULT:\n" + "\n".join(script["votes"])
    if "Register / RSVP" in text:
        return "RESULT: FAILED sold out" if "fail.example" in text else "RESULT: REGISTERED Meetup 2026-10-08"
    if "calendar.google.com" in text:
        return "RESULT: CREATED 2 events\n" + "\n".join(script["created"])
    if "Tell me about your day" in text:
        return "RESULT: " + script["day"]
    if "Draft:" in text:
        return "RESULT: " + script["reply"].pop(0)
    if "Done:" in text:
        return "RESULT: SENT"
    return ""


def _result_lines(out):
    i = out.rfind("RESULT:")
    return [x.strip() for x in out[i + 7:].splitlines() if x.strip()] if i >= 0 else []


fake = types.SimpleNamespace(
    task=_task, result_lines=_result_lines,
    result_line=lambda o: (_result_lines(o) or [""])[0],
    _q=lambda s, n=500: " ".join(str(s).split())[:n].replace('"', "'"),
    whatsapp_ready=lambda: True, calendar_ready=lambda: True,
)

fails: list[str] = []


def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        fails.append(name)


def mk(i, agent, title, kind, url=""):
    item = {"text": title, "hours": 1, "kind": kind, "start": f"2026-10-0{i}T09:00", "date": f"2026-10-0{i}"}
    if url:
        item["url"] = url
    return cardlib.make_card(i, agent, title, 0.9 - i / 10, "r", [], item)


goal_engine.context = lambda agent, g: ""
goal_engine.decompose = lambda g, p, c: goal_engine.decompose_default(g)
goal_engine.change_plan = lambda g, m, p: ([mk(1, "content", "Post a weekly write-up", "post")], "test")
goal_engine.alignment = lambda g, acts: (0.5, "test")
agent_app.planner_agent.run = lambda s, p, sid, day=None, week=False: [mk(sid, "planner", "Deep security study block", "calendar"), mk(sid + 1, "planner", "Lab practice session", "calendar")]
agent_app.events_agent.run = lambda ag, s, p, start_id: [mk(start_id, "events", "AI Security Meetup (2026-10-08)", "rsvp", "https://ok.example/e1"), mk(start_id + 1, "events", "Red Team Night (2026-10-09)", "rsvp", "https://fail.example/e2")]
_drafts: list[str] = []
router.complete = lambda task, msgs, json_schema=None, default=None: (_drafts.append(msgs[-1]["content"]), "My week in security\n\nBody paragraph one.\n\nBody two.")[1]


class _Ev:
    def __init__(self):
        self.out = []

    def emit(self, e):
        self.out.append(e)


def run(text):
    ag = types.SimpleNamespace(events=_Ev(), prompt=text)
    ctx = types.SimpleNamespace(state={}, run_id=0, series_id=0, run_config={})
    rep = agent_app.handle(ag, ctx, text)
    return ag, ctx, rep


def streamed(ag):
    return "".join(e.get("delta", "") for e in ag.events.out)


check("intent demo", agent_app.intent("/demo", {}) == "demo" and agent_app.intent("demo", {"goal": {}}) == "demo")

# Hub: SECOND_BRAIN_LOCAL unset -> real _aside() is None; a fake that would record calls must stay silent
agent_app._on_path = lambda: True
ag, ctx, rep = run("My goal: land an AI security role by December")
check("hub set_goal silent", not calls and "Decision cards" in rep)
ag, ctx, rep = run("/demo")
check("hub demo prints dry texts", not calls and "dry run" in rep and "<CALENDAR_ACCOUNT>" in rep and "[SB-1]" in rep and "[SB-4]" in rep)

# local: dry mode when env is missing (aside present but no numbers/account)
os.environ["SECOND_BRAIN_LOCAL"] = "1"
agent_app._aside = lambda: fake
ag, ctx, rep = run("/demo")
check("no env: dry mode, no aside call", not calls and "dry run" in rep)

# local live run through set_goal
os.environ.update(WHATSAPP_TO="self", CALENDAR_ACCOUNT="acct@example.invalid")
script["votes"] = ["deep security study block", "AI Security Meetup (2026-10-08)", "Red Team Nite (2026-10-09)"]  # 1 lowercase, 1 exact, 1 fuzzy
script["created"] = ["Deep security study block", "AI Security Meetup"]
script["reply"] = ["EDIT shorter please", "POSTED https://x.substack.example/p/1"]
ag, ctx, rep = run("My goal: land an AI security role by December")
sess = runtime.load_state(ctx, "session", {})
by = {c["title"]: c for c in sess["cards"]}
d = sess.get("demo") or {}
check("approval by exact + fuzzy title", by["Deep security study block"]["status"] in ("approved", "executed") and by["Red Team Night (2026-10-09)"]["status"] in ("skipped", "approved"))
check("unvoted plan card skipped", by["Lab practice session"]["status"] == "skipped")
check("register marks", by["AI Security Meetup (2026-10-08)"].get("registered") and by["Red Team Night (2026-10-09)"].get("register_failed") and by["Red Team Night (2026-10-09)"]["status"] == "skipped")
check("calendar marks executed", by["Deep security study block"]["status"] == "executed" and by["Deep security study block"].get("calendar_event") and by["AI Security Meetup (2026-10-08)"]["status"] == "executed")
check("edit-once loop then post", sum("Draft:" in c for c in calls) == 2 and d.get("post_url", "").startswith("https://x.substack") and len(_drafts) == 2)
check("no 3rd draft prompt", sum("Draft:" in c for c in calls) <= 2)
check("demo record", d.get("registered") == ["AI Security Meetup (2026-10-08)"] and d.get("calendar") == 2 and set(d.get("steps", {})) >= {"1", "2", "3", "4", "5"})
check("steps streamed", all(f"Step {k}/5:" in streamed(ag) for k in range(1, 6)) and "RESULT:" in streamed(ag))
check("done task text", any("Done: registered 1 events, 2 calendar blocks, Substack: https://x.substack.example/p/1" in c for c in calls))
check("account in task only", any("acct@example.invalid" in c for c in calls) and "acct@example.invalid" not in rep and "acct@example.invalid" not in streamed(ag))
check("no hashtags/quotes in embedded body", not any("#" in c for c in calls if "Draft:" in c))
full = recaplib.build(sess, runtime.load_profile())
check("recap demo block", "Registered for event: AI Security Meetup" in full and "Calendar blocks added: 2" in full and "Substack post: https://x.substack.example/p/1" in full)

# no vote -> stops, cards stay pending, nothing registered/posted
calls.clear()
script["votes"] = []
script["reply"] = ["POSTED https://nope"]
ag, ctx, rep = run("My goal: land an AI security role by December")
sess = runtime.load_state(ctx, "session", {})
check("no votes stops flow", len(calls) == 1 and "No votes" in rep and all(c["status"] == "pending" for c in sess["cards"]))

# post only when the reply says post; skip / second edit -> no url
for reply in (["SKIPPED"], ["EDIT a", "EDIT b"]):
    calls.clear()
    script.update(votes=["Deep security study block"], created=["Deep security study block"], reply=list(reply))
    ag, ctx, rep = run("My goal: land an AI security role by December")
    sess = runtime.load_state(ctx, "session", {})
    check(f"no post on {reply[-1]}", sess["demo"]["post_url"] is None and any("Substack: skipped" in c for c in calls))

# empty day reply -> no draft, still done
calls.clear()
script.update(votes=["Deep security study block"], day="", created=["Deep security study block"])
ag, ctx, rep = run("My goal: land an AI security role by December")
check("no day reply: no draft", not any("Draft:" in c for c in calls) and any("Done:" in c for c in calls))

print("FAILED: " + ", ".join(fails) if fails else "demo flow OK")
raise SystemExit(1 if fails else 0)
