"""Hand-rolled RFC5545 iCalendar writer (one VEVENT per file, floating local time)."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone


def _esc(s: str) -> str:
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", str(s)).replace("\r\n", "\n").replace("\r", "\n")
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


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
    parsed = _dt(start_iso)
    try:
        h = float(hours)
        h = h if h == h and h != float("inf") else 1.0
    except (TypeError, ValueError):
        h = 1.0
    h = min(max(h, 0.25), 24 * 7)
    aware = parsed.tzinfo is not None
    start = parsed.astimezone(timezone.utc).replace(tzinfo=None) if aware else parsed  # aware -> UTC 'Z'; naive -> floating local
    z = "Z" if aware else ""
    end = start + timedelta(hours=h)
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
        f"DTSTART:{start.strftime(fmt)}{z}",
        f"DTEND:{end.strftime(fmt)}{z}",
        f"SUMMARY:{_esc(title)}",
    ]
    if description:
        lines.append(f"DESCRIPTION:{_esc(description)}")
    if url and re.fullmatch(r"https?://[^\s\x00-\x1f\x7f]+", str(url)):
        lines.append(f"URL:{url}")
    lines += ["END:VEVENT", "END:VCALENDAR"]
    out: list[str] = []
    for ln in lines:
        out += _fold(ln)
    return "\r\n".join(out) + "\r\n"
