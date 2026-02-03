# =========================
# FILE: agent/planner.py
# =========================
import re
from typing import Optional
from agent.schema import Command

def plan(utter: str) -> Optional[Command]:
    raw = utter.strip()
    t = raw.lower().strip()
    
    # Sanitize: remove trailing punctuation from the entire input
    t = re.sub(r'[.,;!?]+$', '', t).strip()
    raw = re.sub(r'[.,;!?]+$', '', raw).strip()
    
    # Smart gibberish detection and correction
    # Detect patterns like "youtubeXXXXX" and auto-extract known app names
    words = t.split()
    for word in words:
        # If word is long (>15 chars), has no dots (not a package), check for app names
        if len(word) > 15 and '.' not in word:
            # Check for excessive consonant clusters (sign of gibberish)
            consonant_clusters = re.findall(r'[bcdfghjklmnpqrstvwxyz]{4,}', word)
            if consonant_clusters:
                # Try to extract potential app name from the start (quietly)
                common_apps = ['youtube', 'gmail', 'chrome', 'maps', 'photos', 'drive', 
                              'calendar', 'messages', 'phone', 'settings', 'camera', 
                              'whatsapp', 'instagram', 'facebook', 'twitter', 'spotify']
                for app in common_apps:
                    if word.startswith(app):
                        # Auto-correct silently
                        t = t.replace(word, app)
                        raw = raw.replace(word, app, 1)
                        print(f"💡 Auto-corrected '{word}' → '{app}'")
                        break

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

    # **NEW: Learning commands**
    if t == "teach":
        return Command(action="TEACH_LAST")
    
    if t.startswith("teach "):
        rest = raw[6:].strip()
        # Pattern: "teach <shortcut> <app>"
        # Examples: "teach google chrome", "teach music spotify"
        parts = rest.split(None, 1)
        if len(parts) == 2:
            return Command(action="TEACH_CUSTOM", query=parts[0], text=parts[1])
        else:
            # Just "teach google" - teach the last opened app with this shortcut
            return Command(action="TEACH_SHORTCUT", query=parts[0])
    
    if t.startswith("forget "):
        return Command(action="FORGET_MAPPING", query=raw[7:].strip())
    
    if t in ("list mappings", "show mappings", "my mappings", "mappings"):
        return Command(action="LIST_MAPPINGS")

    # Existing commands
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

    # **NEW: Vision-based queries**
    # Info queries: "what do you see?", "describe screen", "list videos"
    if any(word in t for word in ["what", "describe", "list", "show me", "tell me"]):
        return Command(action="SCREEN_INFO", query=raw)
    
    # Visual element queries: "click red button", "tap the car image", "first video"
    # Complex queries that need vision or smart routing
    if any(word in t for word in ["click", "tap", "select", "choose", "find"]):
        # Extract what comes after the action verb
        for verb in ["click", "tap", "select", "choose", "find"]:
            if t.startswith(verb):
                target = raw[len(verb):].strip()
                if target:
                    return Command(action="VISION_QUERY", query=target)
    
    # Catch-all for complex queries
    if len(t.split()) > 2:  # Multi-word query likely needs vision
        return Command(action="VISION_QUERY", query=raw)

    return None
