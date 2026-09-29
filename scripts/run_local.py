"""Run Second Brain on your laptop, on top of Aside, without the Flower runtime.

Usage (from the repo root):
    uv run python scripts/run_local.py                      # interactive REPL
    uv run python scripts/run_local.py --once "My goal: land an AI security role by December" "approve 1, 3, skip 4"
    uv run python scripts/run_local.py --embed              # also serve embed + /recap page on http://localhost:8765/recap
    uv run python scripts/run_local.py --embed-only         # only the embed/recap service (blocking)
    uv run python scripts/run_local.py --no-aside ...       # never launch Aside; approved cards only produce briefs

REPL: type a goal, then reply to the cards ("approve 1, 3, pick 2b, skip 4"). Extra commands:
    confirm <session_id>   user OKs the final click -> `aside session steer <id> ...`
    stop <session_id>      abandon it            -> `aside session stop <id>`
    sessions               list pending confirmations;  help;  quit

Keys are optional (data/.env or environment: FIREWORKS_API_KEY, ANTHROPIC_API_KEY). With none, rules + model2vec are used.
Safety: an approved rsvp/post card runs `aside exec` with a brief that must stop BEFORE the final click and answer
'AT FINAL STEP: ...'; a confirmation card is shown and nothing is submitted until you type `confirm <session_id>`.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["SECOND_BRAIN_LOCAL"] = "1"
os.environ.setdefault("SECOND_BRAIN_DATA", str(ROOT / "data"))
os.environ.setdefault("PYTHONUTF8", "1")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from second_brain import agent_app, runtime  # noqa: E402
from second_brain.executor import aside as aside_exec  # noqa: E402
from second_brain.executor import base as executor_base  # noqa: E402

PENDING: dict[str, dict] = {}  # session_id -> aside result awaiting confirm/stop
_RESULTS: list[dict] = []
_THREADS: list[threading.Thread] = []
_LOCK = threading.Lock()


class _Connectors:
    def tools(self, names=None):
        raise RuntimeError("connectors not available in local mode")

    def call(self, *a, **k):
        raise RuntimeError("connectors not available in local mode")


class LocalAgent:
    """Stand-in for flwr AgentSession: prompt, events.emit, connectors."""

    def __init__(self, prompt: str = "") -> None:
        self.prompt = prompt
        self.connectors = _Connectors()
        self.events = SimpleNamespace(emit=self._emit)

    @staticmethod
    def _emit(event: dict) -> None:
        if event.get("type") == "response.output_text.delta":
            print(event.get("delta", ""), end="", flush=True)


class LocalContext:
    def __init__(self) -> None:
        self.state: dict = {}
        self.run_config: dict = {}


def _install_executor_hook(use_aside: bool) -> None:
    """Approved briefs run in background threads so the REPL stays responsive; results are queued for display."""
    real_run = executor_base.run

    def hooked(brief: dict) -> dict:
        if not use_aside:
            return real_run(brief)
        if not brief or "ACTION BRIEF" not in (brief.get("text") or ""):
            return {"ok": False, "status": "rejected", "reason": "no approved brief"}
        label = f"card {brief.get('card_id')}"

        def work() -> None:
            res = aside_exec.run(brief)
            res["label"] = label
            with _LOCK:
                _RESULTS.append(res)

        t = threading.Thread(target=work, daemon=True, name=f"aside-{label}")
        t.start()
        _THREADS.append(t)
        print(f"[aside] started for {label} (stops before the final click)", flush=True)
        return {"ok": True, "status": "queued"}

    executor_base.run = hooked


def flush_results() -> None:
    with _LOCK:
        items, _RESULTS[:] = list(_RESULTS), []
    for r in items:
        sid = r.get("session_id") or "?"
        print(f"\n[aside {r['label']}] status={r['status']} session={sid}")
        if r["status"] == "confirm":
            PENDING[sid] = r
            card = r["card"]
            print(f"  CONFIRM: {card['title']} - {card['detail'][:400]}\n  -> `confirm {sid}` to let Aside do the final click, `stop {sid}` to abandon.")
        else:
            print("  " + (r.get("output") or "")[-600:].replace("\n", "\n  "))


def wait_pending(limit: float = aside_exec.TIMEOUT + 10) -> None:
    t0 = time.time()
    while any(t.is_alive() for t in _THREADS) and time.time() - t0 < limit:
        time.sleep(0.5)
    flush_results()


def start_embed() -> None:
    def serve() -> None:
        try:
            from second_brain.local import embed_service

            embed_service.main()
        except Exception as e:  # noqa: BLE001
            print(f"[embed] not started: {e}", flush=True)

    threading.Thread(target=serve, daemon=True, name="embed").start()
    for _ in range(30):  # wait up to ~15s for /health
        if runtime._reachable(os.environ.get("EMBED_SERVICE", "http://localhost:8765") + "/health"):
            print("[embed] up: http://localhost:8765/recap", flush=True)
            return
        time.sleep(0.5)
    print("[embed] did not come up (recap page unavailable; everything else still works)", flush=True)


def command(line: str) -> bool:
    """Return True if handled as a REPL command."""
    parts = line.split()
    if not parts:
        return True
    cmd = parts[0].lower()
    if cmd in ("confirm", "stop") and len(parts) == 2:
        sid = parts[1]
        fn = aside_exec.approve if cmd == "confirm" else aside_exec.skip
        rc, out = fn(sid)
        print(f"[aside {cmd} {sid}] rc={rc} {out[:300]}")
        PENDING.pop(sid, None)
        return True
    if cmd == "sessions":
        print("\n".join(f"{s}: {r['card']['detail'][:100]}" for s, r in PENDING.items()) or "(no pending confirmations)")
        return True
    if cmd == "help":
        print(__doc__)
        return True
    return False


def turn(agent_ctx: tuple, text: str) -> None:
    _, context = agent_ctx
    agent = LocalAgent(text)
    try:
        print(agent_app.handle(agent, context, text))
    except Exception as e:  # noqa: BLE001
        print(f"Something went wrong: {type(e).__name__}: {e}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Run Second Brain locally on top of Aside")
    ap.add_argument("--once", nargs="+", metavar="PROMPT", help="run these prompts in order, then exit")
    ap.add_argument("--embed", action="store_true", help="start the embed/recap service on :8765 in the background")
    ap.add_argument("--embed-only", action="store_true", help="only run the embed/recap service (blocking)")
    ap.add_argument("--no-aside", action="store_true", help="do not launch Aside for approved cards")
    ap.add_argument("--fresh", action="store_true", help="reset saved session state first (keeps profile)")
    a = ap.parse_args()

    runtime.load_env()
    if a.embed_only:
        from second_brain.local import embed_service

        print("embed service on http://localhost:8765 (recap: /recap)")
        embed_service.main()
        return 0
    if a.embed:
        start_embed()
    if a.fresh:
        (runtime.data_dir() / "session.json").unlink(missing_ok=True)
    have_aside = bool(shutil.which("aside")) and not a.no_aside
    print(f"[local] mode={runtime.mode()} aside={'yes' if have_aside else 'no'} keys={[k for k in ('FIREWORKS_API_KEY', 'ANTHROPIC_API_KEY') if os.environ.get(k)] or 'none (rules + model2vec)'}")
    _install_executor_hook(have_aside)
    ctx = (None, LocalContext())

    if a.once:
        for p in a.once:
            print(f"\n>>> {p}\n")
            if not command(p):
                turn(ctx, p)
        if have_aside and _THREADS:
            print("\n[aside] waiting for browser tasks (max ~160s)...")
            wait_pending()
        return 0

    print("Second Brain (local). Type a goal, e.g. 'My goal: land an AI security role by December'. `help` for commands.")
    while True:
        flush_results()
        try:
            line = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if line.lower() in ("quit", "exit", "q"):
            return 0
        if not command(line):
            turn(ctx, line)


if __name__ == "__main__":
    raise SystemExit(main())
