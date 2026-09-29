"""Second Brain AgentApp: goal -> milestones -> decision cards -> user decides -> briefs -> recap."""

from __future__ import annotations

import re
import time
from typing import Any

from flwr.agentapp import AgentApp, AgentSession
from flwr.app import Context

from . import cards as cardlib
from . import goal_engine, recap as recaplib, router, runtime
from .agents import content as content_agent
from .agents import events as events_agent
from .agents import health as health_agent
from .agents import planner as planner_agent
from .executor import base as executor_base
from .executor import briefs as briefslib

app = AgentApp()


def say(agent: AgentSession, text: str) -> None:
    """Stream the answer so it shows in Flower Chat, and echo to logs."""
    for i in range(0, len(text), 400):
        agent.events.emit({"type": "response.output_text.delta", "delta": text[i : i + 400]})
    agent.events.emit({"type": "response.completed", "response": {"status": "completed"}})
    print(text)


def intent(text: str, session: dict) -> str:
    """Rule-first intent; the flower model only breaks ties."""
    t = text.lower()
    if cardlib.has_decisions(t) and any(c["status"] == "pending" for c in session.get("cards", [])):
        return "decide"
    if re.match(r"\s*(my )?goal\b|\s*i want to\b", t):
        return "set_goal"
    if re.search(r"\bslept\b|\bsleep\b|\bworked out\b|\bworkout\b", t):
        return "health"
    if re.search(r"plan (my )?(tomorrow|day|week)|\bplanner\b|\bcalendar block", t):
        return "planner"
    if re.search(r"recap event|\bphotos?\b|\bwrite (a )?post\b|^\s*post\b", t):
        return "content"
    if re.search(r"\bgoal\b|\bi want to\b|\bland\b", t) or not session.get("goal"):
        return "set_goal"
    if re.search(r"\bevents?\b|\bmeetups?\b|\bfind\b", t):
        return "events"
    if re.search(r"\brecap\b|\bsummary\b", t):
        return "recap"
    return "other"


def _activities(profile: dict, cards: list[dict]) -> list[dict]:
    return profile.get("activities", []) + [c["item"] for c in cards if c["status"] == "approved"]


def _summary(session: dict, profile: dict) -> str:
    g = session["goal"]["goal"]
    before = session.get("alignment_before")
    after, _ = goal_engine.alignment(g, _activities(profile, session.get("cards", [])))
    lines = [f"**Goal:** {g}  | **Alignment:** {before} -> {after}"]
    for c in session.get("cards", []):
        lines.append(f"- {c['id']}. {c['title']}: {c['status']}" + (f" (picked: {c['chosen']})" if c.get("chosen") else ""))
    return "\n".join(lines)


def handle(agent: AgentSession, context: Context, text: str) -> str:
    profile = runtime.load_profile()
    session = runtime.load_state(context, "session", {}) or {}
    kind = intent(text, session)
    runtime.log({"task": "intent", "intent": kind, "mode": runtime.mode()})

    if kind == "set_goal":
        goal = goal_engine.capture(text)
        ctx = goal_engine.context(agent, goal["goal"])
        miles = goal_engine.decompose(goal, profile, ctx)
        cards, backend = goal_engine.change_plan(goal, miles, profile)
        before, be = goal_engine.alignment(goal["goal"], profile.get("activities", []))
        goal_engine.log_alignment("before", before, be)
        session = {"started": time.time(), "goal": goal, "milestones": miles, "cards": cards, "alignment_before": before, "scorer": backend}
        out = [f"**Goal:** {goal['goal']} (by {goal['deadline']}) - why: {goal['why'] or 'n/a'}", "", "**Milestones**"]
        out += [f"- {m['title']} (by {m['by']}): {m['weekly']}" for m in miles]
        out += ["", f"Alignment of your current routine with this goal: **{before}** (scorer: {backend})", "", cardlib.render(cards)]
        reply = "\n".join(out)
    elif kind == "decide":
        cardlib.apply(session["cards"], cardlib.parse_reply(text), profile)
        runtime.save_profile(profile)
        after, be = goal_engine.alignment(session["goal"]["goal"], _activities(profile, session["cards"]))
        session["alignment_after"] = after
        goal_engine.log_alignment("after", after, be)
        reply = "Recorded your decisions.\n\n" + _summary(session, profile)
        issued = briefslib.issue(session)
        for b in issued:
            executor_base.run(b)  # hub: hands the brief back; never submits
        if issued:
            reply += "\n\n**Action briefs** (paste into your browser agent; each stops before the final step)\n\n" + "\n\n".join(b["text"] for b in issued)
        else:
            reply += "\n\n(No approved cards, so no briefs.)"
        reply += "\n\n" + recaplib.build(session, profile)
    elif kind == "health":
        session.setdefault("cards", [])
        entries, new = health_agent.run(text, profile, len(session["cards"]) + 1)
        runtime.save_profile(profile)
        session["cards"] += new
        logged = ", ".join(f"{e['kind']}={e['value']:g}" for e in entries) or "nothing I could parse"
        reply = f"Logged: {logged}."
        if new:
            reply += "\n\n" + cardlib.render(new)
    elif kind in ("planner", "content"):
        if not session.get("goal"):
            reply = "Tell me your goal first (e.g. 'My goal: land an AI security role by December')."
        elif kind == "planner":
            new = planner_agent.run(session, profile, len(session["cards"]) + 1)
            session["cards"] += new
            reply = ("Goal-aligned calendar blocks:\n\n" + cardlib.render(new)) if new else "No block fits your constraints tomorrow."
        else:
            new = content_agent.run(agent, session, profile, len(session["cards"]) + 1, text)
            session["cards"] += new
            reply = "Post drafts (with photo picks):\n\n" + cardlib.render(new)
    elif kind == "events":
        new = events_agent.run(agent, session, profile, start_id=len(session["cards"]) + 1)
        session["cards"] += new
        reply = "Ranked events for your goal:\n\n" + cardlib.render(new)
    elif kind == "recap":
        reply = recaplib.build(session, profile)
    else:
        reply = "Tell me your goal (e.g. 'My goal: land an AI security role by December'), or reply to the cards with `approve 1, 3, pick 2b, skip 4`."
    runtime.save_state(context, "session", session)
    return reply


@app.main()
def main(agent: AgentSession, context: Context) -> None:
    runtime.load_env()
    router.configure(context.run_config)
    try:
        say(agent, handle(agent, context, agent.prompt))
    except Exception as e:  # noqa: BLE001 - never leave the chat silent
        runtime.log({"task": "error", "error": str(e)[:300]})
        say(agent, f"Something went wrong: {e}")
