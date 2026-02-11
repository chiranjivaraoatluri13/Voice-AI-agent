# =========================
# FILE: agent/planner.py
# =========================
"""
Context-aware command planner — v5 NLP.

INTENT CLASSIFICATION via keyword sets:
  words = set(utterance.split())
  if words & VOLUME_WORDS and words & UP_WORDS → VOLUME_UP

Any word order works. No regex needed for semantic intents.
"""

import re
from typing import Optional, List
from agent.schema import Command

# ===========================================================
# KEYWORD SETS — define what words signal each intent
# ===========================================================
VOLUME_WORDS = {"volume", "sound", "audio", "speaker"}
UP_WORDS = {"up", "increase", "raise", "louder", "higher", "more", "boost", "amplify"}
DOWN_WORDS = {"down", "decrease", "lower", "softer", "quieter", "less", "reduce", "dim"}
BIG_WORDS = {"lot", "max", "full", "way", "maximum", "completely"}

CLOSE_WORDS = {"close", "clear", "kill", "end", "terminate"}
ALL_WORDS = {"all", "every", "everything", "recent", "recents"}
APPS_WORDS = {"apps", "app", "tasks", "windows"}

SCROLL_WORDS = {"scroll", "swipe", "slide", "flip", "page"}
PLAY_WORDS = {"play", "resume", "continue", "unpause"}
PAUSE_WORDS = {"pause", "halt", "freeze"}
NEXT_WORDS = {"next", "skip", "forward"}
PREV_WORDS = {"previous", "prev", "rewind"}

MEDIA_TAP_APPS = {
    "com.google.android.youtube", "com.instagram.android",
    "com.zhiliaoapp.musically", "com.snapchat.android",
}
MESSAGING_APPS = [
    "whatsapp", "messaging", "messenger", "telegram", "snapchat",
    "signal", "viber", "wechat", "line", "kakaotalk",
]
CONTENT_APP_CONTEXTS = {
    "com.whatsapp": {"contact", "chat", "group", "person", "message"},
    "com.whatsapp.w4b": {"contact", "chat", "group", "person", "message"},
    "com.google.android.youtube": {"video", "channel", "playlist", "shorts"},
    "com.pinterest": {"pin", "board", "idea"},
    "com.instagram.android": {"post", "reel", "story", "profile"},
    "com.google.android.gm": {"email", "mail", "message", "inbox"},
    "com.google.android.apps.messaging": {"message", "conversation", "chat"},
    "com.samsung.android.messaging": {"message", "conversation", "chat"},
    "com.snapchat.android": {"snap", "story", "chat"},
}
APP_ACTIONS = {
    "take a picture": {"desc": ["Shutter", "Capture", "Take photo"], "key": "KEYCODE_CAMERA"},
    "take a photo": {"desc": ["Shutter", "Capture", "Take photo"], "key": "KEYCODE_CAMERA"},
    "click a picture": {"desc": ["Shutter", "Capture", "Take photo"], "key": "KEYCODE_CAMERA"},
    "click a photo": {"desc": ["Shutter", "Capture", "Take photo"], "key": "KEYCODE_CAMERA"},
    "capture": {"desc": ["Shutter", "Capture", "Take photo"], "key": "KEYCODE_CAMERA"},
    "take a selfie": {"desc": ["Shutter", "Capture", "Take photo"], "key": "KEYCODE_CAMERA"},
    "record video": {"desc": ["Record", "Start recording", "Video"]},
    "flip camera": {"desc": ["Switch camera", "Flip", "Front camera"]},
    "switch camera": {"desc": ["Switch camera", "Flip", "Front camera"]},
    "screenshot": {"key": "KEYCODE_SYSRQ"},
    "take a screenshot": {"key": "KEYCODE_SYSRQ"},
}


# ===========================================================
# MAIN ENTRY
# ===========================================================
def plan(utter: str, current_app: str = "", **kwargs) -> Optional[Command]:
    raw = utter.strip()
    t = raw.lower().strip()
    if not t:
        return None
    words = set(t.split())

    # ── MULTI-STEP: "open camera click a picture and open gallery" ──
    steps = _split_multi_step(t)
    if steps and len(steps) > 1:
        return Command(action="MULTI_STEP", text=raw, query="|".join(steps))

    # ── EXACT SINGLE-WORD / SHORT COMMANDS ──
    if t in ("exit", "quit"):
        return Command(action="EXIT")
    if t in ("back", "go back"):
        return Command(action="BACK")
    if t in ("home", "go home", "home screen"):
        return Command(action="HOME")
    if t in ("wake", "wake up"):
        return Command(action="WAKE")
    if t in ("backspace", "erase", "delete"):
        return Command(action="KEYEVENT", query="KEYCODE_DEL")
    if t in ("enter", "return", "submit", "press enter"):
        return Command(action="KEYEVENT", query="KEYCODE_ENTER")
    if "reindex" in t or ("refresh" in t and "app" in t):
        return Command(action="REINDEX_APPS")

    # ── CLOSE ALL (keyword-set: close/clear/kill + all/apps/everything) ──
    if words & CLOSE_WORDS and (words & ALL_WORDS or words & APPS_WORDS):
        return Command(action="CLOSE_ALL")

    # ── LEARNING ──
    if t == "teach":
        return Command(action="TEACH_LAST")
    if t.startswith("teach "):
        rest = raw[6:].strip()
        parts = rest.split(None, 1)
        return Command(action="TEACH_CUSTOM", query=parts[0], text=parts[1]) if len(parts) == 2 \
            else Command(action="TEACH_SHORTCUT", query=parts[0])
    if t.startswith("forget "):
        return Command(action="FORGET_MAPPING", query=raw[7:].strip())
    if t in ("list mappings", "show mappings", "my mappings", "mappings"):
        return Command(action="LIST_MAPPINGS")

    # ── COMPOUND: "type/write X and send", "send X" ──
    compound = _parse_compound(t, raw, current_app)
    if compound:
        return compound

    # ── VOLUME (keyword-set NLP: any order) ──
    vol = _parse_volume(t, words)
    if vol:
        return vol

    # ── SCROLL / SWIPE ──
    scroll = _parse_scroll_swipe(t, words)
    if scroll:
        return scroll

    # ── TYPE / WRITE ──
    if t.startswith("type ") or t.startswith("write "):
        pfx = 5 if t[0] == 't' else 6
        msg = raw[pfx:].strip()
        return Command(action="TYPE_TEXT", text=msg) if msg else None

    # ── TAP coordinates ──
    m = re.match(r"tap\s+(\d+)\s+(\d+)$", t)
    if m:
        return Command(action="TAP", x=int(m.group(1)), y=int(m.group(2)))

    # ── OPEN Nth CONTENT IN APP ──
    content = _parse_open_content(t, raw, current_app)
    if content:
        return content

    # ── MEDIA (keyword-set NLP) ──
    media = _parse_media(t, words, current_app)
    if media:
        return media

    # ── MESSAGING: "send X to Y on Z" ──
    msg = _parse_messaging(t, raw)
    if msg:
        return msg

    # ── APP ACTIONS: "take a picture", "screenshot" ──
    for phrase, info in APP_ACTIONS.items():
        if phrase in t:
            return Command(action="APP_ACTION", query=phrase,
                           text="|".join(info.get("desc", [])),
                           package=info.get("key", ""))

    # ── OPEN APP ──
    open_m = re.match(r'(?:open|launch|start|run|go to|switch to)\s+(.+)', t)
    if open_m:
        return _resolve_open(_clean(open_m.group(1)), current_app)

    # ── ORDINAL: "select the first post" ──
    ord_m = re.match(
        r'(?:click|tap|select|press|hit|choose|open|play)\s+(?:on\s+)?(?:the\s+)?'
        r'(first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th|last)\s+(.+)', t)
    if ord_m:
        return Command(action="VISION_QUERY", query=f"the {ord_m.group(1)} {ord_m.group(2).strip()}")

    # ── CLICK/TAP <target> ──
    for verb in ["click", "tap", "select", "press", "hit", "choose"]:
        if t.startswith(verb + " "):
            target = _clean(raw[len(verb):].strip())
            target = re.sub(r'^on\s+', '', target, flags=re.I)
            if target:
                return Command(action="VISION_QUERY", query=target)

    # ── SEARCH ──
    search_m = re.match(r'(?:search|look|find)\s+(?:for\s+)?(.+?)(?:\s+(?:on|in)\s+(.+))?$', t)
    if search_m:
        return Command(action="SEARCH_IN_APP", query=search_m.group(1).strip(),
                       text=search_m.group(2).strip() if search_m.group(2) else None)

    # ── SCREEN INFO ──
    if any(kw in t for kw in ["what do you see", "what's on screen", "describe screen",
                               "what is this", "tell me what"]):
        return Command(action="SCREEN_INFO", query=raw)

    # ── CATCH-ALL → vision ──
    return Command(action="VISION_QUERY", query=raw)


# ===========================================================
# MULTI-STEP SPLITTER
# ===========================================================
def _split_multi_step(t: str) -> Optional[List[str]]:
    """Split "open camera click picture and open gallery" → 3 steps."""
    action_verbs = {"open", "click", "tap", "select", "close", "search",
                    "type", "write", "send", "play", "take", "capture", "go"}

    # First split on "and then" / "then" / "and" between action phrases
    parts = re.split(r'\s+(?:and\s+then|then)\s+', t)
    if len(parts) >= 2:
        valid = [p.strip() for p in parts if p.strip()]
        if len(valid) >= 2:
            return valid

    # Split on "and" only if both sides start with action verbs
    parts = re.split(r'\s+and\s+', t)
    if len(parts) >= 2:
        valid = [p.strip() for p in parts if p.strip()]
        verb_parts = [p for p in valid if p.split()[0] in action_verbs]
        if len(verb_parts) >= 2:
            return valid

    # Detect consecutive action verbs: "open camera click picture"
    wds = t.split()
    splits = []
    prev = 0
    for i, w in enumerate(wds):
        if i > 0 and w in action_verbs:
            chunk = " ".join(wds[prev:i]).strip()
            if chunk:
                splits.append(chunk)
            prev = i
    if splits:
        last = " ".join(wds[prev:]).strip()
        if last:
            splits.append(last)
        if len(splits) >= 2:
            return splits

    return None


# ===========================================================
# COMPOUND
# ===========================================================
def _parse_compound(t: str, raw: str, current_app: str) -> Optional[Command]:
    m = re.match(r'(?:type|write)\s+(.+?)\s+and\s+(?:send|submit|send it|press send)', t)
    if m:
        return Command(action="TYPE_AND_SEND", text=m.group(1).strip())
    m = re.match(r'(?:type|write)\s+(.+?)\s+and\s+(?:press\s+)?(?:enter|return|submit)', t)
    if m:
        return Command(action="TYPE_AND_ENTER", text=m.group(1).strip())
    if t in ("send", "send it"):
        return Command(action="TAP_SEND")
    m = re.match(r'send\s+(.+)', t)
    if m:
        msg = m.group(1).strip()
        if re.search(r'\bto\b', msg):
            return None
        return Command(action="TYPE_AND_SEND", text=msg)
    return None


# ===========================================================
# VOLUME (keyword-set)
# ===========================================================
def _parse_volume(t: str, words: set) -> Optional[Command]:
    has_vol = bool(words & VOLUME_WORDS) or "turn" in t
    has_up = bool(words & UP_WORDS)
    has_down = bool(words & DOWN_WORDS)
    big = bool(words & BIG_WORDS)

    if t in ("louder",):
        return Command(action="VOLUME_UP", amount=2)
    if t in ("quieter", "softer"):
        return Command(action="VOLUME_DOWN", amount=2)
    if "louder" in t or "crank" in t:
        return Command(action="VOLUME_UP", amount=5 if big else 2)
    if "quieter" in t or "softer" in t:
        return Command(action="VOLUME_DOWN", amount=5 if big else 2)
    if has_vol and has_up:
        return Command(action="VOLUME_UP", amount=5 if big else 2)
    if has_vol and has_down:
        return Command(action="VOLUME_DOWN", amount=5 if big else 2)
    if "turn" in t and has_up:
        return Command(action="VOLUME_UP", amount=2)
    if "turn" in t and has_down:
        return Command(action="VOLUME_DOWN", amount=2)
    if words & {"mute", "silence"} or "shut up" in t:
        return Command(action="VOLUME_DOWN", amount=10)
    return None


# ===========================================================
# SCROLL / SWIPE (keyword-set)
# ===========================================================
def _parse_scroll_swipe(t: str, words: set) -> Optional[Command]:
    if not (words & SCROLL_WORDS):
        return None
    is_swipe = bool(words & {"swipe", "slide", "flip"})

    if "down" in t:
        d = "DOWN"
    elif "up" in t:
        d = "UP"
    elif "left" in t:
        d = "LEFT"
    elif "right" in t:
        d = "RIGHT"
    else:
        d = "DOWN"

    amt = 1
    if any(w in t for w in ["twice", "two", "2"]):
        amt = 2
    elif any(w in t for w in ["more", "lot", "fast", "three", "3"]):
        amt = 3

    return Command(action="SWIPE" if is_swipe else "SCROLL", direction=d, amount=amt)


# ===========================================================
# MEDIA (keyword-set NLP)
# ===========================================================
def _parse_media(t: str, words: set, current_app: str) -> Optional[Command]:
    is_tap = current_app and any(a in current_app for a in MEDIA_TAP_APPS)
    is_media = current_app and any(a in current_app for a in
        ["youtube", "spotify", "music", "vlc", "mx", "video", "instagram", "tiktok"])

    if words & PAUSE_WORDS:
        return Command(action="MEDIA_PLAY_PAUSE") if is_tap else Command(action="MEDIA_PAUSE")
    if words & {"stop"} and is_media:
        return Command(action="MEDIA_PLAY_PAUSE") if is_tap else Command(action="MEDIA_PAUSE")
    if words & PLAY_WORDS:
        if any(kw in t for kw in ["play store", "playstore"]):
            return None
        if words & {"first", "second", "third", "fourth", "fifth", "1st", "2nd", "3rd"}:
            return None  # Let ordinal handler do it
        return Command(action="MEDIA_PLAY_PAUSE") if is_tap else Command(action="MEDIA_PLAY")
    if words & NEXT_WORDS:
        return Command(action="SCROLL", direction="DOWN", amount=1) if is_tap else Command(action="MEDIA_NEXT")
    if words & PREV_WORDS:
        return Command(action="SCROLL", direction="UP", amount=1) if is_tap else Command(action="MEDIA_PREVIOUS")
    return None


# ===========================================================
# CONTENT / MESSAGING / HELPERS
# ===========================================================
def _parse_open_content(t: str, raw: str, current_app: str) -> Optional[Command]:
    ords = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
            "1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5, "last": -1}
    m = re.match(
        r'(?:open|play|tap|click|select)\s+(?:the\s+)?(\w+)\s+'
        r'(video|reel|post|shorts?|pin|result|item|song|track|episode)\b'
        r'(?:\s+(?:in|on|from)\s+(.+))?', t)
    if m and m.group(1) in ords:
        app = m.group(3)
        if app:
            return Command(action="OPEN_CONTENT_IN_APP", query=m.group(2),
                         text=app.strip(), amount=ords[m.group(1)])
        return Command(action="VISION_QUERY", query=f"{m.group(1)} {m.group(2)}")
    return None


def _parse_messaging(t: str, raw: str) -> Optional[Command]:
    m = re.match(r'send\s+(.+?)\s+to\s+(.+?)(?:\s+(?:on|in|via)\s+(.+))?$', t)
    if m:
        return Command(action="SEND_MESSAGE", query=m.group(2).strip(),
                       text=m.group(1).strip(), package=m.group(3).strip() if m.group(3) else None)
    m = re.match(r'(?:message|text|whatsapp)\s+(\w+)\s+(?:saying|that|:)\s*(.+)', t)
    if m:
        return Command(action="SEND_MESSAGE", query=m.group(1).strip(),
                       text=m.group(2).strip(), package="whatsapp")
    return None


def _clean(target: str) -> str:
    return re.sub(r'^(?:the|a|an|on|to|at)\s+', '', target.strip(), flags=re.I).strip()


def _resolve_open(target: str, current_app: str) -> Command:
    tl = target.lower()
    if current_app:
        for pkg, types in CONTENT_APP_CONTEXTS.items():
            if pkg in current_app:
                if any(ct in tl for ct in types):
                    return Command(action="VISION_QUERY", query=target)
                app_words = {"app", "store", "play", "chrome", "browser", "gmail",
                            "youtube", "maps", "settings", "camera", "gallery",
                            "clock", "calculator", "calendar", "notes", "files",
                            "spotify", "instagram", "pinterest", "whatsapp",
                            "telegram", "snapchat", "twitter", "facebook", "netflix"}
                if not any(w in tl for w in app_words):
                    if any(m in current_app for m in
                           ["whatsapp", "messaging", "messenger", "telegram",
                            "snapchat", "contacts", "dialer", "instagram"]):
                        return Command(action="VISION_QUERY", query=target)
    return Command(action="OPEN_APP", query=target)
