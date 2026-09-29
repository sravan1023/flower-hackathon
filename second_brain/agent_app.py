"""Second Brain AgentApp: goal -> milestones -> decision cards -> user decides -> briefs -> recap."""

from __future__ import annotations

import re
import threading
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


_SEQ = 0
DEADLINE_S = 150  # hard cap on one turn; the chat always gets an answer before this
BEAT_S = 20
PLAN_JOIN_S = 100


def _emit(agent: AgentSession, event: dict) -> None:
    """emit() raises on a closed/failed publisher; never let that kill or silence the run."""
    global _SEQ
    _SEQ += 1
    try:
        agent.events.emit({**event, "sequence_number": _SEQ})
    except Exception as e:  # noqa: BLE001
        print(f"[emit failed] {e}", flush=True)


def delta(agent: AgentSession, text: str) -> None:
    """Visible streamed text (the shape flwr chat / the web chat render)."""
    for i in range(0, len(text), 400):
        _emit(agent, {"type": "response.output_text.delta", "item_id": "msg_sb", "output_index": 0, "content_index": 0, "delta": text[i : i + 400]})


def finish(agent: AgentSession, text: str) -> None:
    """Terminal event the chat waits for; exactly once per run."""
    msg = {"type": "message", "id": "msg_sb", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": text, "annotations": []}]}
    _emit(agent, {"type": "response.completed", "response": {"id": "resp_sb", "object": "response", "status": "completed", "output": [msg]}})


def say(agent: AgentSession, text: str) -> None:
    """Stream the answer so it shows in Flower Chat, then complete; echo to logs."""
    delta(agent, text)
    finish(agent, text)
    print(text, flush=True)


def intent(text: str, session: dict) -> str:
    """Rule-first intent; the flower model only breaks ties."""
    t = text.lower()
    if cardlib.has_decisions(t):
        return "decide"  # handle() explains when there is no goal or no pending card
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


def _next_id(session: dict) -> int:
    return max([c["id"] for c in session.get("cards", [])] or [0]) + 1


def _model_line() -> str:
    """Which provider answered last (router.LAST_PROVIDER when present), else rule-based."""
    return f"model: {getattr(router, 'LAST_PROVIDER', None) or 'rule-based'}"


def _activities(profile: dict, cards: list[dict]) -> list[dict]:
    return profile.get("activities", []) + [c["item"] for c in cards if c["status"] == "approved"]


def _summary(session: dict, profile: dict) -> str:
    g = (session.get("goal") or {}).get("goal", "(no goal set)")
    before = session.get("alignment_before")
    after, _ = goal_engine.alignment(g, _activities(profile, session.get("cards", [])))
    lines = [f"**Goal:** {g}  | **Alignment:** {before} -> {after}"]
    for c in session.get("cards", []):
        lines.append(f"- {c['id']}. {c['title']}: {c['status']}" + (f" (picked: {c['chosen']})" if c.get("chosen") else ""))
    return "\n".join(lines)


def _probe() -> str:
    """`!probe`: call the runtime model exactly like the scaffold does and report raw outcomes (diagnostics)."""
    import os
    import time

    from openai import OpenAI

    out = [f"model={router._model('flower')} base={os.environ.get('FLWR_RUNTIME_BASE_URL', '?')[:60]}"]
    variants = {
        "scaffold-style stream": dict(input=[{"type": "message", "role": "user", "content": "Reply with the word ok."}], stream=True),
        "plain-role stream": dict(input=[{"role": "user", "content": "Reply with the word ok."}], stream=True),
        "string input no stream": dict(input="Reply with the word ok."),
    }
    for name, kw in variants.items():
        t0 = time.time()
        try:
            c = OpenAI(base_url=os.environ["FLWR_RUNTIME_BASE_URL"], api_key=os.environ["FLWR_RUNTIME_API_KEY"], max_retries=0, timeout=25)
            r = c.responses.create(model=router._model("flower"), **kw)
            if kw.get("stream"):
                types = [e.type for e in r]
                out.append(f"{name}: OK {time.time() - t0:.1f}s events={types[:6]}...{len(types)}")
            else:
                out.append(f"{name}: OK {time.time() - t0:.1f}s text={r.output_text[:40]!r}")
        except Exception as e:  # noqa: BLE001
            out.append(f"{name}: FAIL {time.time() - t0:.1f}s {type(e).__name__}: {str(e)[:200]}")
    return "\n".join(out)


def handle(agent: AgentSession, context: Context, text: str) -> str:
    if text.strip() == "!probe":
        return _probe()
    profile = runtime.load_profile()
    session = runtime.load_state(context, "session", {}) or {}
    kind = intent(text, session)
    runtime.log({"task": "intent", "intent": kind, "mode": runtime.mode()})

    if kind == "set_goal":
        runtime.stage("capture")
        goal = goal_engine.capture(text)
        runtime.stage("context")
        ctx = goal_engine.context(agent, goal["goal"])
        runtime.stage("decompose+change_plan")
        # two independent LLM calls in parallel (change_plan must not wait for decompose); each falls back to defaults
        box: dict[str, Any] = {}

        def _run(key: str, fn: Any) -> None:
            try:
                box[key] = fn()
            except BaseException as e:  # noqa: BLE001
                runtime.log({"task": key, "error": str(e)[:200]})

        th = [threading.Thread(target=_run, args=("decompose", lambda: goal_engine.decompose(goal, profile, ctx)), daemon=True),
              threading.Thread(target=_run, args=("change_plan", lambda: goal_engine.change_plan(goal, None, profile)), daemon=True)]
        for x in th:
            x.start()
        for x in th:
            x.join(PLAN_JOIN_S)
        miles = box.get("decompose") or goal_engine.decompose_default(goal)
        cards, backend = box.get("change_plan") or goal_engine.change_plan_default(goal, profile)
        runtime.stage("alignment")
        before, be = goal_engine.alignment(goal["goal"], profile.get("activities", []))
        runtime.stage("done")
        goal_engine.log_alignment("before", before, be)
        session = {"started": time.time(), "goal": goal, "milestones": miles, "cards": cards, "alignment_before": before, "scorer": backend}
        out = [f"**Goal:** {goal['goal']} (by {goal['deadline']}) - why: {goal['why'] or 'n/a'}", "", "**Milestones**"]
        out += [f"- {m['title']} (by {m['by']}): {m['weekly']}" for m in miles]
        out += ["", f"Alignment of your current routine with this goal: **{before}** (scorer: {backend})", _model_line(), "", cardlib.render(cards)]
        reply = "\n".join(out)
    elif kind == "decide" and not session.get("goal"):
        reply = "Tell me your goal first (e.g. 'My goal: land an AI security role by December'), then I can show cards to decide on."
    elif kind == "decide" and not any(c.get("status") == "pending" for c in session.get("cards", [])):
        reply = "There are no pending cards to decide on. Ask me to plan tomorrow, find events, or post about an event to get some."
    elif kind == "decide":
        cardlib.apply(session["cards"], cardlib.parse_reply(text), profile)
        runtime.save_profile(profile)
        after, be = goal_engine.alignment((session.get("goal") or {}).get("goal", ""), _activities(profile, session["cards"]))
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
        entries, new = health_agent.run(text, profile, _next_id(session))
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
            new = planner_agent.run(session, profile, _next_id(session))
            session["cards"] += new
            reply = ("Goal-aligned calendar blocks:\n\n" + cardlib.render(new)) if new else "No block fits your constraints tomorrow."
        else:
            new = content_agent.run(agent, session, profile, _next_id(session), text)
            session["cards"] += new
            reply = "Post drafts (with photo picks):\n\n" + cardlib.render(new)
    elif kind == "events":
        new = events_agent.run(agent, session, profile, start_id=_next_id(session))
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
    runtime.stage("start")
    delta(agent, "Working on it...\n\n")  # immediate visible output; results follow
    box: dict[str, Any] = {}

    def work() -> None:
        try:
            runtime.load_env()
            try:
                router.configure(context.run_config)
            except Exception as e:  # noqa: BLE001 - run config is optional
                runtime.log({"task": "configure", "error": str(e)[:200]})
            box["reply"] = handle(agent, context, agent.prompt)
        except BaseException as e:  # noqa: BLE001 - never leave the chat silent
            runtime.log({"task": "error", "error": str(e)[:300]})
            box["error"] = e

    t = threading.Thread(target=work, name="second-brain-turn", daemon=True)
    t.start()
    t0 = time.time()
    while t.is_alive() and time.time() - t0 < DEADLINE_S:
        t.join(BEAT_S)
        if t.is_alive() and time.time() - t0 < DEADLINE_S:
            delta(agent, f"(still working, {int(time.time() - t0)}s)\n")
    runtime.stage("finish")
    if "reply" in box:
        say(agent, box["reply"])
    elif "error" in box:
        say(agent, f"Something went wrong: {box['error']}")
    else:
        say(agent, f"That took longer than {DEADLINE_S}s, so I stopped. Please retry (a simpler goal statement helps); providers or connectors may be slow.")
