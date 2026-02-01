# =========================
# FILE: agent/planner.py
# =========================
import re
from typing import Optional
from agent.schema import Command

def plan(utter: str) -> Optional[Command]:
    raw = utter.strip()
    t = raw.lower().strip()

    if not t:
        return None

    if t in ("exit", "quit", "stop"):
        return Command(action="EXIT")

    if t in ("wake", "wake up"):
        return Command(action="WAKE")

    if t in ("reindex apps", "refresh apps", "reload apps"):
        return Command(action="REINDEX_APPS")

    if t in ("back", "go back"):
        return Command(action="BACK")

    if t in ("home", "go home"):
        return Command(action="HOME")

    if t.startswith("find "):
        return Command(action="FIND_APP", query=raw[5:].strip())

    if t.startswith("open "):
        return Command(action="OPEN_APP", query=raw[5:].strip())

    if "scroll down" in t:
        amt = 2 if ("more" in t or "twice" in t) else 1
        return Command(action="SCROLL", direction="DOWN", amount=amt)

    if "scroll up" in t:
        amt = 2 if ("more" in t or "twice" in t) else 1
        return Command(action="SCROLL", direction="UP", amount=amt)

    if t.startswith("type "):
        msg = raw[5:].strip()
        if not msg:
            return None
        return Command(action="TYPE_TEXT", text=msg)

    m = re.match(r"tap\s+(\d+)\s+(\d+)$", t)
    if m:
        return Command(action="TAP", x=int(m.group(1)), y=int(m.group(2)))

    return None
