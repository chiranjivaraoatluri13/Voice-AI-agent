# =========================
# FILE: agent/planner_enhanced.py  
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
    words = t.split()
    for word in words:
        if len(word) > 15 and '.' not in word:
            consonant_clusters = re.findall(r'[bcdfghjklmnpqrstvwxyz]{4,}', word)
            if consonant_clusters:
                common_apps = ['youtube', 'gmail', 'chrome', 'maps', 'photos', 'drive', 
                              'calendar', 'messages', 'phone', 'settings', 'camera', 
                              'whatsapp', 'instagram', 'facebook', 'twitter', 'spotify']
                for app in common_apps:
                    if word.startswith(app):
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

    # ===========================
    # VOLUME CONTROLS (NEW)
    # ===========================
    
    # Volume up
    if any(phrase in t for phrase in ["volume up", "increase volume", "louder", "turn up", "raise volume"]):
        # Check for amount
        amount = 1
        if "a lot" in t or "way" in t or "max" in t or "maximum" in t:
            amount = 5
        elif "little" in t or "bit" in t or "slightly" in t:
            amount = 1
        elif "more" in t:
            amount = 2
        
        return Command(action="VOLUME_UP", amount=amount)
    
    # Volume down
    if any(phrase in t for phrase in ["volume down", "decrease volume", "quieter", "turn down", "lower volume", "reduce volume"]):
        amount = 1
        if "a lot" in t or "way" in t:
            amount = 5
        elif "little" in t or "bit" in t or "slightly" in t:
            amount = 1
        elif "more" in t:
            amount = 2
        
        return Command(action="VOLUME_DOWN", amount=amount)
    
    # Set specific volume
    # Patterns: "set volume to 50", "volume 75", "set volume 30"
    volume_match = re.search(r'(?:set\s+)?volume\s+(?:to\s+)?(\d+)', t)
    if volume_match:
        level = int(volume_match.group(1))
        return Command(action="SET_VOLUME", amount=level)
    
    # Mute
    if t in ("mute", "silence", "turn off sound", "no sound"):
        return Command(action="VOLUME_MUTE")
    
    # ===========================
    # MEDIA CONTROLS (NEW)
    # ===========================
    
    # Play (THIS IS THE KEY FIX FOR YOUR VIDEO ISSUE)
    if t in ("play", "start playing", "resume", "continue", "unpause"):
        return Command(action="MEDIA_PLAY")
    
    # Play/Pause toggle
    if t in ("play pause", "pause play", "toggle playback", "playpause"):
        return Command(action="MEDIA_PLAY_PAUSE")
    
    # Pause
    if t in ("pause", "stop playing", "hold"):
        return Command(action="MEDIA_PAUSE")
    
    # Stop
    if t in ("stop", "stop playback", "stop media"):
        return Command(action="MEDIA_STOP")
    
    # Next
    if any(phrase in t for phrase in ["next", "skip", "next video", "next song", "next track"]):
        return Command(action="MEDIA_NEXT")
    
    # Previous
    if any(phrase in t for phrase in ["previous", "prev", "last", "go back", "previous video", "previous song"]):
        return Command(action="MEDIA_PREVIOUS")
    
    # Fast forward
    if any(phrase in t for phrase in ["fast forward", "forward", "skip ahead", "ff"]):
        return Command(action="MEDIA_FAST_FORWARD")
    
    # Rewind
    if any(phrase in t for phrase in ["rewind", "go back", "rew"]):
        return Command(action="MEDIA_REWIND")

    # ===========================
    # LEARNING COMMANDS
    # ===========================
    
    if t == "teach":
        return Command(action="TEACH_LAST")
    
    if t.startswith("teach "):
        rest = raw[6:].strip()
        parts = rest.split(None, 1)
        if len(parts) == 2:
            return Command(action="TEACH_CUSTOM", query=parts[0], text=parts[1])
        else:
            return Command(action="TEACH_SHORTCUT", query=parts[0])
    
    if t.startswith("forget "):
        return Command(action="FORGET_MAPPING", query=raw[7:].strip())
    
    if t in ("list mappings", "show mappings", "my mappings", "mappings"):
        return Command(action="LIST_MAPPINGS")

    # ===========================
    # APP COMMANDS
    # ===========================
    
    if t.startswith("find "):
        return Command(action="FIND_APP", query=raw[5:].strip())

    if t.startswith("open "):
        return Command(action="OPEN_APP", query=raw[5:].strip())

    # ===========================
    # NAVIGATION COMMANDS
    # ===========================
    
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

    # ===========================
    # VISION QUERIES
    # ===========================
    
    # Info queries
    if any(word in t for word in ["what", "describe", "list", "show me", "tell me"]):
        return Command(action="SCREEN_INFO", query=raw)
    
    # Visual element queries  
    if any(word in t for word in ["click", "tap", "select", "choose", "find"]):
        for verb in ["click", "tap", "select", "choose", "find"]:
            if t.startswith(verb):
                target = raw[len(verb):].strip()
                if target:
                    return Command(action="VISION_QUERY", query=target)
    
    # Catch-all for complex queries
    if len(t.split()) > 2:
        return Command(action="VISION_QUERY", query=raw)

    return None
