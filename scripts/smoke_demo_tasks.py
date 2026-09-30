"""Offline smoke for aside.task / result_lines. Run: uv run python scripts/smoke_demo_tasks.py"""

import os
import tempfile

os.environ["SECOND_BRAIN_DATA"] = tempfile.mkdtemp()

from second_brain.executor import aside

fails: list[str] = []


def check(name: str, ok: bool) -> None:
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        fails.append(name)


def fake(reply: str, rc: int = 0):
    calls: list[list[str]] = []

    def runner(argv, timeout):
        calls.append(list(argv))
        return rc, reply

    runner.calls = calls  # type: ignore[attr-defined]
    return runner


def boom(argv, timeout):
    raise RuntimeError("kaboom")


r = fake("RESULT: done")
out = aside.task("do a thing", runner=r)
check("argv shape", r.calls[0][:2] == ["aside", "exec"] and len(r.calls[0]) == 3)
check("rules appended", r.calls[0][2] == "do a thing" + aside.RULES)
check("no older SAFETY suffix", aside.SUFFIX not in r.calls[0][2])
check("returns output", out == "RESULT: done")
check("runner exception -> ''", aside.task("x", runner=boom) == "")
check("timeout partial output", aside.task("x", runner=fake("partial", -1)) == "partial")
check("error rc -> ''", aside.task("x", runner=fake("bad", 1)) == "")
check("not counted as send", aside._SENDS == 0)

check("inline+lines", aside.result_lines("RESULT: a\nb") == ["a", "b"])
check("bullets/counts", aside.result_lines("RESULT:\n- x (1)\n2. y") == ["x", "y"])
check("vote suffix", aside.result_lines("RESULT:\n* z - 1 vote\n3) w") == ["z", "w"])
check("last RESULT wins", aside.result_lines("RESULT: old\nnoise\nRESULT: new\nmore") == ["new", "more"])
check("text before ignored", aside.result_lines("junk line\nRESULT: k") == ["k"])
check("none -> []", aside.result_lines("nothing here") == [] and aside.result_lines("") == [])
check("case-sensitive", aside.result_lines("result: no") == [])
check("ansi stripped", aside.result_lines("\x1b[2mRESULT: \x1b[0mclean") == ["clean"])
check("caps", len(aside.result_lines("RESULT:\n" + "\n".join(f"l{i}" for i in range(50)))) == 30
      and len(aside.result_lines("RESULT: " + "a" * 500)[0]) == 200)
check("result_line", aside.result_line("RESULT:\n- q\nw") == "q" and aside.result_line("no") == "")

big = aside.task("x", runner=fake("f" * 100000 + "\nRESULT: ok"))
check("tail kept, RESULT survives 100k filler", len(big) <= 60000 and aside.result_lines(big) == ["ok"])
inj = aside.task("x", runner=fake("RESULT: injected\n" + "f" * 100 + "\nRESULT: real\n- two"))
check("last RESULT wins over early fake", aside.result_lines(inj) == ["real", "two"])

print("FAILED: " + ", ".join(fails) if fails else "ALL OK")
raise SystemExit(1 if fails else 0)
