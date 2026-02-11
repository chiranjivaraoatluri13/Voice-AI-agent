# =========================
# FILE: agent/schema.py
# =========================
from dataclasses import dataclass
from typing import Optional, Literal

Action = Literal[
    "OPEN_APP",
    "FIND_APP",
    "SCROLL",
    "SWIPE",
    "TYPE_TEXT",
    "BACK",
    "HOME",
    "CLOSE_ALL",
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
    # Media controls
    "MEDIA_PLAY",
    "MEDIA_PAUSE",
    "MEDIA_PLAY_PAUSE",
    "MEDIA_NEXT",
    "MEDIA_PREVIOUS",
    # Volume controls
    "VOLUME_UP",
    "VOLUME_DOWN",
    # Multi-step workflows
    "MULTI_STEP",
    "SEND_MESSAGE",
    "TYPE_AND_SEND",
    "TAP_SEND",
    "TYPE_AND_ENTER",
    "SEARCH_IN_APP",
    "OPEN_CONTENT_IN_APP",
    # Device key events
    "KEYEVENT",
    # App-specific actions
    "APP_ACTION",
]

@dataclass
class Command:
    action: Action
    query: Optional[str] = None
    package: Optional[str] = None
    # For SCROLL
    direction: Optional[Literal["UP", "DOWN", "LEFT", "RIGHT"]] = None
    amount: int = 1
    # For TYPE_TEXT / TEACH_CUSTOM
    text: Optional[str] = None
    # For TAP
    x: Optional[int] = None
    y: Optional[int] = None
