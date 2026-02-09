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
    # Learning actions
    "TEACH_LAST",           # Teach the last opened app
    "TEACH_CUSTOM",         # Teach custom mapping: teach <shortcut> <app>
    "TEACH_SHORTCUT",       # Teach shortcut for last app
    "FORGET_MAPPING",       # Forget a learned mapping
    "LIST_MAPPINGS",        # Show all learned mappings
    # Vision actions
    "VISION_QUERY",         # Complex vision-based query
    "SCREEN_INFO",          # "What do you see?"
    "FIND_VISUAL",          # Find by visual description
    # Media controls
    "MEDIA_PLAY",
    "MEDIA_PAUSE",
    "MEDIA_NEXT",
    "MEDIA_PREVIOUS",
    # Volume controls
    "VOLUME_UP",
    "VOLUME_DOWN",
]

@dataclass
class Command:
    action: Action
    # For OPEN_APP / FIND_APP / FORGET_MAPPING
    query: Optional[str] = None
    package: Optional[str] = None  # when we already know the package
    # For SCROLL
    direction: Optional[Literal["UP", "DOWN"]] = None
    amount: int = 1
    # For TYPE_TEXT / TEACH_CUSTOM (text is the target app for teaching)
    text: Optional[str] = None
    # For TAP
    x: Optional[int] = None
    y: Optional[int] = None
