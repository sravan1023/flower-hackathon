"""Second Brain AgentApp: goal -> milestones -> decision cards -> user decides -> briefs -> recap."""

from __future__ import annotations

import re
from typing import Any

from flwr.agentapp import AgentApp, AgentSession
from flwr.app import Context

from . import cards as cardlib
from . import goal_engine, router, runtime
from .agents import events as events_agent

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
        session = {"goal": goal, "milestones": miles, "cards": cards, "alignment_before": before, "scorer": backend}
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
        reply = "Recorded your decisions.\n\n" + _summary(session, profile) + "\n\n(Briefs for approved cards: coming in the next build.)"
    elif kind == "events":
        new = events_agent.run(agent, session, profile, start_id=len(session["cards"]) + 1)
        session["cards"] += new
        reply = "Ranked events for your goal:\n\n" + cardlib.render(new)
    elif kind == "recap":
        reply = _summary(session, profile)
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
