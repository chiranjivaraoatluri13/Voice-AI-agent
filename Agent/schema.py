# =========================
# FILE: agent/schema.py
# =========================
from dataclasses import dataclass
from typing import Optional, Literal

Action = Literal[
    "OPEN_APP",
    "FIND_APP",
    "SCROLL",
    "TYPE_TEXT",
    "BACK",
    "HOME",
    "TAP",
    "WAKE",
    "REINDEX_APPS",
    "EXIT",
]

@dataclass
class Command:
    action: Action
    # For OPEN_APP / FIND_APP
    query: Optional[str] = None
    package: Optional[str] = None  # when we already know the package
    # For SCROLL
    direction: Optional[Literal["UP", "DOWN"]] = None
    amount: int = 1
    # For TYPE_TEXT
    text: Optional[str] = None
    # For TAP
    x: Optional[int] = None
    y: Optional[int] = None
