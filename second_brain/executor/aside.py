"""Local-mode executor: drives the `aside` CLI. Output is untrusted data: truncated, sanitised, never executed.

run(brief) -> {"session_id", "status": done|confirm|error|timeout, "output", "card"?}
A fake subprocess runner can be injected (runner=callable(argv, timeout)->(rc, stdout)) for tests.
"""

from __future__ import annotations

import re
import subprocess
from typing import Any, Callable

from .. import cards, runtime

TIMEOUT = 150
MAX_OUT = 4000
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_SESSION = re.compile(r"Created new session:\s*([A-Za-z0-9_\-]+)")

Runner = Callable[[list[str], int], tuple[int, str]]


def clean(text: str, limit: int = MAX_OUT) -> str:
    text = _CTRL.sub("", _ANSI.sub("", text or ""))
    return text if len(text) <= limit else text[:limit] + "...[truncated]"


def _default_runner(argv: list[str], timeout: int) -> tuple[int, str]:
    p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _call(argv: list[str], runner: Runner | None, timeout: int = TIMEOUT) -> tuple[int, str]:
    """Run one aside command; never raises. rc -1 = timeout, -2 = cannot start."""
    try:
        rc, out = (runner or _default_runner)(argv, timeout)
    except subprocess.TimeoutExpired:
        rc, out = -1, "timeout"
    except Exception as e:  # noqa: BLE001
        rc, out = -2, f"{type(e).__name__}: {e}"
    out = clean(out)
    runtime.log({"task": "aside", "argv": [clean(a, 200) for a in argv[:4]], "rc": rc, "out": out[:200]})
    return rc, out


def parse_session_id(output: str) -> str | None:
    m = _SESSION.search(output or "")
    return m.group(1) if m else None


def at_final_step(output: str) -> bool:
    return "at final step" in (output or "").lower()


def confirmation_card(session_id: str, brief: str, output: str, cid: int = 0) -> dict:
    card = cards.make_card(
        cid,
        "executor",
        "Confirm final step in browser",
        1.0,
        "Aside stopped before the final click; needs your approval",
        [],
        item={"text": clean(brief, 200), "hours": 0, "kind": "aside-confirm", "session_id": session_id},
        detail=clean(output, 800),
    )
    card["session_id"] = session_id
    return card


def run(brief: str, runner: Runner | None = None) -> dict[str, Any]:
    _call(["aside", "--update"], runner)
    _call(["aside", "guide"], runner)
    rc, out = _call(["aside", "exec", brief], runner)
    sid = parse_session_id(out)
    if rc == -1:
        return {"session_id": sid, "status": "timeout", "output": out}
    if rc != 0:
        return {"session_id": sid, "status": "error", "output": out}
    if at_final_step(out):
        return {"session_id": sid, "status": "confirm", "output": out, "card": confirmation_card(sid or "", brief, out)}
    return {"session_id": sid, "status": "done", "output": out}


def approve(session_id: str, runner: Runner | None = None) -> tuple[int, str]:
    return _call(["aside", "session", "steer", session_id, "Approved, click it, then report"], runner)


def skip(session_id: str, runner: Runner | None = None) -> tuple[int, str]:
    return _call(["aside", "session", "stop", session_id], runner)
