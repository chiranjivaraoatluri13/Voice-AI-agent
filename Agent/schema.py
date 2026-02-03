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
    "TEACH_LAST",
    "TEACH_CUSTOM",
    "TEACH_SHORTCUT",
    "FORGET_MAPPING",
    "LIST_MAPPINGS",
    # Vision actions
    "VISION_QUERY",
    "SCREEN_INFO",
    "FIND_VISUAL",
    # Volume controls (NEW)
    "VOLUME_UP",
    "VOLUME_DOWN",
    "SET_VOLUME",
    "VOLUME_MUTE",
    # Media controls (NEW)
    "MEDIA_PLAY",
    "MEDIA_PAUSE",
    "MEDIA_PLAY_PAUSE",
    "MEDIA_STOP",
    "MEDIA_NEXT",
    "MEDIA_PREVIOUS",
    "MEDIA_FAST_FORWARD",
    "MEDIA_REWIND",
]

@dataclass
class Command:
    action: Action
    # For OPEN_APP / FIND_APP / FORGET_MAPPING
    query: Optional[str] = None
    package: Optional[str] = None
    # For SCROLL / VOLUME
    direction: Optional[Literal["UP", "DOWN"]] = None
    amount: int = 1
    # For TYPE_TEXT / TEACH_CUSTOM
    text: Optional[str] = None
    # For TAP
    x: Optional[int] = None
    y: Optional[int] = None
