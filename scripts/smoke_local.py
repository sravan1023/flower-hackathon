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
assert [c[1] for c in r.calls] == ["--update", "guide", "exec"], r.calls

# 2. final step -> card, no click
r = fake(lambda a: (0, "Created new session: s9\nAgent is at final step: Submit") if a[1] == "exec" else (0, ""))
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
