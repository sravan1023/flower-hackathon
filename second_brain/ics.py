"""Hand-rolled RFC5545 iCalendar writer (one VEVENT per file, floating local time)."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone


def _esc(s: str) -> str:
    return str(s).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r", "").replace("\n", "\\n")


def _fold(line: str) -> list[str]:
    """Fold to <=75 octets per line; continuation lines start with one space."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return [line]
    out, cur, size = [], "", 0
    for ch in line:
        n = len(ch.encode("utf-8"))
        limit = 75 if not out else 74
        if size + n > limit:
            out.append(cur)
            cur, size = "", 0
        cur += ch
        size += n
    out.append(cur)
    return [out[0]] + [" " + x for x in out[1:]]


def _dt(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


def make_ics(title: str, start_iso: str, hours: float, description: str = "", url: str = "") -> str:
    start = _dt(start_iso).replace(tzinfo=None)
    end = start + timedelta(hours=max(float(hours), 0.25))
    uid = hashlib.sha1(f"{title}|{start_iso}".encode()).hexdigest()[:20] + "@second-brain"
    fmt = "%Y%m%dT%H%M%S"
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//second-brain//flower agentapp//EN",
        "CALSCALE:GREGORIAN",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{datetime.now(timezone.utc).strftime(fmt)}Z",
        f"DTSTART:{start.strftime(fmt)}",
        f"DTEND:{end.strftime(fmt)}",
        f"SUMMARY:{_esc(title)}",
    ]
    if description:
        lines.append(f"DESCRIPTION:{_esc(description)}")
    if url and re.match(r"https?://", url):
        lines.append(f"URL:{url}")
    lines += ["END:VEVENT", "END:VCALENDAR"]
    out: list[str] = []
    for ln in lines:
        out += _fold(ln)
    return "\r\n".join(out) + "\r\n"
