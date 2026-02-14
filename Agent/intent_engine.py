# =========================
# FILE: agent/intent_engine.py
# =========================
"""
3-Tier Intent Engine — Natural Language Understanding for Voice Agent.

Architecture:
  TIER 1 — TF-IDF (~2ms): Handles 80% of commands instantly.
           High-confidence semantic matching against knowledge base.

  TIER 2 — LLM Fallback (~300-800ms): Only fires when TF-IDF is unsure.
           Uses local Ollama model for true language understanding.
           "blast it" → LLM understands → VOLUME_UP amount=MAX

  TIER 3 — Self-Learning Cache: Every LLM result gets cached back into
           TF-IDF. Second time you say "blast it" → instant.
           Agent gets faster the more you use it.

Voice Pipeline:
  [Whisper STT ~500ms] → [Tier1 TF-IDF ~2ms] → [Execute ~200ms]
                               ↓ (uncertain)
                         [Tier2 LLM ~500ms] → [Tier3 Cache] → [Execute]

  After caching: ALL commands become Tier 1 speed.

Latency Guarantees:
  - Known commands: <5ms (TF-IDF)
  - New phrasing (first time): 300-800ms (LLM, then cached)
  - New phrasing (second time): <5ms (cached in TF-IDF)
"""

import re
import math
import json
import os
import time
import threading
from typing import Optional, List, Dict, Tuple
from collections import Counter
from agent.schema import Command


# =========================================================
# ACTION KNOWLEDGE BASE
# =========================================================

ACTION_EXAMPLES: Dict[str, List[str]] = {
    # --- Navigation ---
    "EXIT": [
        "exit", "quit", "stop agent", "close agent", "shut down agent",
        "bye", "goodbye", "end session", "terminate agent",
    ],
    "WAKE": [
        "wake", "wake up", "turn on screen", "wake screen",
        "light up screen", "activate screen", "screen on",
    ],
    "BACK": [
        "back", "go back", "previous", "navigate back",
        "return", "press back", "go to previous", "go previous",
    ],
    "HOME": [
        "home", "go home", "home screen", "main screen",
        "go to home", "press home", "go to home screen",
    ],
    "CLOSE_ALL": [
        "close all", "close all apps", "clear recent", "clear recents",
        "close everything", "kill all apps", "clear all apps",
    ],
    "CLOSE_APP": [
        "close it", "close this", "close this app", "close app",
        "close the app", "close current app", "kill this app",
        "exit app", "exit this app", "quit app",
    ],

    # --- Volume ---
    "VOLUME_UP": [
        "volume up", "louder", "increase volume", "make it louder",
        "turn up volume", "raise volume", "more volume",
        "increase sound", "crank it up", "sound louder",
        "turn it up", "boost volume", "pump up volume",
    ],
    "VOLUME_DOWN": [
        "volume down", "quieter", "decrease volume", "make it quieter",
        "turn down volume", "lower volume", "less volume",
        "decrease sound", "reduce volume", "softer",
        "turn it down", "not so loud",
    ],
    "VOLUME_MAX": [
        "max volume", "maximum volume", "full volume", "volume max",
        "volume full", "blast it", "loudest", "loudest possible",
        "all the way up", "volume all the way up", "volume 100",
        "as loud as it goes", "crank it all the way",
        "max the volume", "put volume to maximum",
        "full blast", "set volume to max", "turn it all the way up",
    ],
    "VOLUME_MIN": [
        "minimum volume", "volume minimum", "lowest volume",
        "volume to lowest", "barely audible",
    ],
    "VOLUME_MUTE": [
        "mute", "sound off", "silence", "be quiet", "shut up",
        "turn off sound", "mute sound", "mute volume", "volume mute",
        "no sound", "go silent", "silent mode", "sound mute",
        "mute audio", "kill sound", "quiet", "hush",
    ],
    "VOLUME_UNMUTE": [
        "unmute", "sound on", "turn on sound", "unmute sound",
        "unmute volume", "restore sound", "bring back sound",
    ],

    # --- Media ---
    "MEDIA_PLAY": [
        "play", "play music", "resume", "resume music",
        "start playing", "continue playing", "unpause",
        "resume playback", "put on some music", "play something",
    ],
    "MEDIA_PAUSE": [
        "pause", "pause music", "stop music", "stop playing",
        "hold music", "pause playback",
    ],
    "MEDIA_PLAY_PAUSE": [
        "play pause", "toggle play", "play or pause", "toggle playback",
    ],
    "MEDIA_NEXT": [
        "next", "next song", "next track", "skip", "skip song",
        "skip track", "play next", "skip this", "change song",
    ],
    "MEDIA_PREVIOUS": [
        "previous", "previous song", "previous track",
        "go back song", "last song", "play previous", "previous please",
    ],

    # --- Scrolling ---
    "SCROLL_DOWN": [
        "scroll down", "scroll", "go down", "page down",
        "more content", "keep scrolling", "scroll more",
    ],
    "SCROLL_UP": [
        "scroll up", "go up", "page up", "scroll to top",
        "back up", "scroll back up",
    ],
    "SCROLL_LEFT": [
        "scroll left", "go left",
    ],
    "SCROLL_RIGHT": [
        "scroll right", "go right",
    ],
    "SWIPE_LEFT": [
        "swipe left", "swipe away", "dismiss", "next page",
    ],
    "SWIPE_RIGHT": [
        "swipe right", "previous page", "swipe back",
    ],

    # --- App Management ---
    "OPEN_APP": [
        "open youtube", "open whatsapp", "open chrome", "open settings",
        "open gmail", "open spotify", "open camera", "open instagram",
        "open telegram", "open maps", "open calculator", "open calendar",
        "open phone", "open contacts", "open gallery", "open photos",
        "launch youtube", "launch whatsapp", "launch chrome",
        "launch spotify", "launch camera",
        "start youtube", "start spotify",
        "go to youtube", "go to whatsapp", "go to chrome",
        "go to instagram", "go to settings",
        "run youtube", "switch to whatsapp", "switch to chrome",
        "open the app", "take me to youtube", "take me to whatsapp",
        "take me to my messages", "take me to my photos",
        "show me my gallery", "show me my contacts",
    ],
    "FIND_APP": [
        "find youtube", "find gmail", "find spotify",
        "search for app gmail", "look for spotify",
        "where is chrome", "do i have whatsapp",
    ],
    "REINDEX_APPS": [
        "reindex apps", "refresh apps", "reload apps",
        "rescan apps", "update app list",
    ],

    # --- Typing ---
    "TYPE_TEXT": [
        "type hello", "write hello world", "enter text",
        "input something", "type this",
    ],
    "TYPE_AND_SEND": [
        "write hello and send", "type hello and send",
        "write good morning and hit send",
        "type thanks then send", "type hi and send it",
    ],
    "TYPE_AND_ENTER": [
        "type hello and enter", "type hello and press enter",
        "enter hello and submit", "type cats and search",
    ],
    "TAP_SEND": [
        "send", "hit send", "press send", "tap send",
        "send it", "send message", "submit",
    ],

    # --- Messaging ---
    "SEND_MESSAGE": [
        "send hello to mom", "send hi to mom on whatsapp",
        "send good morning to poojitha on whatsapp",
        "send good morning to poojitha in whatsapp",
        "text poojitha hello on whatsapp",
        "text poojitha hello in whatsapp",
        "message mom saying hello", "message mom",
        "text mom hello", "text mom", "text john",
        "text poojitha", "text dad good morning",
        "tell mom i am coming", "tell dad hello",
        "whatsapp mom hello", "whatsapp dad",
        "whatsapp poojitha good morning",
        "chat with mom", "chat mom", "chat with john",
        "chat with poojitha", "chat poojitha",
        "dm mom", "dm john hello",
        "send a message to mom", "message john on whatsapp",
        "message poojitha hello", "message poojitha on whatsapp",
    ],

    # --- Search ---
    "SEARCH_IN_APP": [
        "search cats on youtube", "search for cats",
        "search cats in chrome", "look up weather",
        "find cats on youtube", "google cats",
        "youtube search funny videos", "search recipes",
        "search for news", "look up restaurants",
        "i want to watch something funny",
        "show me trending stuff",
    ],
    "OPEN_CONTENT_IN_APP": [
        "play first video on youtube", "open second video on youtube",
        "watch third video on youtube", "play first song on spotify",
        "first video on youtube", "second video on youtube",
        "open first post on instagram", "play first reel on instagram",
    ],

    # --- Screen Interaction ---
    "TAP": [
        "tap 540 1200", "click 100 200", "press 300 400",
        "touch 540 960",
    ],
    "VISION_QUERY": [
        # Explicit click/tap
        "click subscribe", "tap the subscribe button",
        "click on the red button", "tap the first video",
        "press the menu icon", "select the option",
        "click the thumbnail", "tap the link",
        "hit the like button", "choose option two",
        "click the play button", "tap the share icon",
        # Natural in-app actions (NO verb prefix — user just says what to do)
        "subscribe", "subscribe to this channel",
        "subscribe to this youtube channel",
        "subscribe the youtube channel",
        "subscribe the channel",
        "like this video", "like the video", "like it",
        "dislike this video", "dislike",
        "share this video", "share this", "share it",
        "save this video", "save this", "save it",
        "comment on this video", "add a comment",
        "follow this account", "follow", "follow them",
        "unfollow", "unsubscribe",
        "download this", "download the video",
        "report this", "report this video",
        "add to playlist", "save to playlist",
        "turn on notifications", "ring the bell",
        "hit the bell icon",
        # Ordinal/position — select Nth item on CURRENT screen
        "select the first video", "select the second video",
        "select the third video", "first video", "second video",
        "third video", "first post", "second post",
        "select the first item", "select the second item",
        "tap the first video", "tap the second video",
        "click on the first one", "click the second one",
        "open the first video", "open the second video",
        # Numeric ordinals: 1st, 2nd, 3rd, 4th, 5th
        "tap on 4th mail", "click the 3rd email", "select 2nd result",
        "tap on 1st item", "open the 5th link",
        "tap on the 4th one", "click the 3rd one",
        "select the 4th mail", "open 3rd message",
        # More item types with word ordinals
        "first mail", "second email", "third message",
        "first result", "second link", "first option",
        "tap the first mail", "click the second email",
        "select first result", "open second link",
    ],
    "SCREEN_INFO": [
        "what do you see", "describe screen", "what is on screen",
        "tell me what you see", "what is visible",
        "describe what is on screen", "read the screen",
        "analyze screen", "what app is this", "where am i",
    ],
    "FIND_VISUAL": [
        "find subscribe on screen", "locate the button",
        "where is the search bar", "look for settings icon",
    ],

    # --- Learning ---
    "TEACH_LAST": [
        "teach", "remember this", "learn this",
    ],
    "TEACH_CUSTOM": [
        "teach google chrome", "teach music spotify",
        "remember google as chrome",
        "when i say browser open chrome",
    ],
    "FORGET_MAPPING": [
        "forget google", "unlearn browser",
        "remove mapping music", "delete shortcut",
    ],
    "LIST_MAPPINGS": [
        "list mappings", "show mappings", "my mappings", "mappings",
        "what have you learned", "show shortcuts",
    ],

    # --- Keyevent ---
    "KEYEVENT": [
        "press enter", "press tab", "press escape",
        "press delete", "press backspace", "press space",
    ],

    # --- System ---
    "BRIGHTNESS_UP": [
        "brightness up", "brighter", "increase brightness",
        "more brightness", "screen brighter",
    ],
    "BRIGHTNESS_DOWN": [
        "brightness down", "dimmer", "decrease brightness",
        "less brightness", "screen dimmer", "dim screen",
    ],
    "SCREENSHOT": [
        "screenshot", "take screenshot", "capture screen",
        "screen capture", "take a screenshot",
    ],
}

# Actions list for LLM prompt (auto-generated)
ALL_ACTIONS = sorted(ACTION_EXAMPLES.keys())


# =========================================================
# COMPOUND COMMAND SPLITTER
# =========================================================

_COMMAND_VERBS = {
    # App control
    "open", "launch", "start", "go", "switch", "close", "kill", "exit",
    # Typing
    "type", "write", "enter", "input",
    # Messaging
    "send", "message", "text", "tell", "chat",
    # Search
    "search", "look", "find", "google", "youtube",
    # Screen interaction
    "click", "tap", "press", "select", "hit",
    # Scrolling
    "scroll", "swipe",
    # Media
    "play", "pause", "stop", "skip", "next", "previous", "resume",
    # Navigation
    "back", "home",
    # Volume/system — CRITICAL for compound commands
    "mute", "unmute", "volume",
    "increase", "decrease", "raise", "lower", "reduce",
    "turn", "set", "max", "crank", "boost", "pump",
    # Learning
    "teach", "forget",
    # Brightness
    "dim", "brighten",
    # Screenshot
    "screenshot", "capture",
}


def split_compound(utterance: str) -> Optional[List[str]]:
    """
    Split 'open chrome and search cats' → ['open chrome', 'search cats']
    Split 'open youtube and close it'  → ['open youtube', 'close it']
    Split 'click thor video and increase volume' → ['click thor video', 'increase volume']
    
    Does NOT split:
      'write hello and send' (send is a modifier, not a new command)
      'type cats and search' (search is a modifier here)
    """
    t = utterance.strip()
    for sep in [" and then ", " then ", " and ", " after that "]:
        if sep not in t.lower():
            continue
        idx = t.lower().index(sep)
        left = t[:idx].strip()
        right = t[idx + len(sep):].strip()
        if not left or not right:
            continue
        
        right_words = right.lower().split()
        first_word = right_words[0] if right_words else ""

        # Single-word right side: only split if it's a STANDALONE command
        # "close it" / "mute" / "pause" = standalone commands (split)
        # "send" / "enter" / "submit" / "search" = modifiers of the left side (don't split)
        if len(right_words) <= 1 and first_word in {"send", "enter", "submit", "search"}:
            continue

        # "tap it" / "click it" / "select it" = refers to same target (don't split)
        # "search for like on screen AND TAP IT" → single action
        if len(right_words) == 2 and right_words[1] in {"it", "that", "this"}:
            if first_word in {"tap", "click", "select", "press", "hit", "open"}:
                continue

        # "tap it" / "click it" / "select it" = refers to same target (don't split)
        # "search for like on screen AND TAP IT" → single action, not two
        if len(right_words) == 2 and right_words[1] in {"it", "that", "this"}:
            if first_word in {"tap", "click", "select", "press", "hit", "open"}:
                continue

        if first_word in _COMMAND_VERBS:
            return [left, right]
    return None


# =========================================================
# TIER 1: TF-IDF MATCHER
# =========================================================

def _tokenize(text: str) -> List[str]:
    tokens = re.findall(r'[a-z0-9]+', text.lower())
    stopwords = {"the", "a", "an", "is", "it", "i", "my", "me",
                 "please", "can", "you", "could", "would"}
    return [t for t in tokens if t not in stopwords and len(t) > 0]


class TFIDFMatcher:
    def __init__(self) -> None:
        self.documents: List[Tuple[str, str]] = []
        self.doc_tokens: List[List[str]] = []
        self.idf: Dict[str, float] = {}
        self.doc_tfidf: List[Dict[str, float]] = []
        self._built = False

    def add_document(self, action: str, text: str) -> None:
        self.documents.append((action, text))
        clean = re.sub(r'\{[^}]+\}', '', text).strip()
        self.doc_tokens.append(_tokenize(clean))
        self._built = False

    def build(self) -> None:
        n = len(self.documents)
        if n == 0:
            return
        df: Counter = Counter()
        for tokens in self.doc_tokens:
            for token in set(tokens):
                df[token] += 1
        self.idf = {
            term: math.log((n + 1) / (freq + 1)) + 1
            for term, freq in df.items()
        }
        self.doc_tfidf = []
        for tokens in self.doc_tokens:
            tf = Counter(tokens)
            total = len(tokens) if tokens else 1
            tfidf = {
                term: (count / total) * self.idf.get(term, 1.0)
                for term, count in tf.items()
            }
            self.doc_tfidf.append(tfidf)
        self._built = True

    def match(self, query: str, top_k: int = 5) -> List[Tuple[float, str, str]]:
        if not self._built:
            self.build()
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []
        tf = Counter(query_tokens)
        total = len(query_tokens)
        query_tfidf = {
            term: (count / total) * self.idf.get(term, 1.0)
            for term, count in tf.items()
        }
        results = []
        for i, doc_vec in enumerate(self.doc_tfidf):
            score = self._cosine(query_tfidf, doc_vec)
            if score > 0:
                action, example = self.documents[i]
                results.append((score, action, example))
        results.sort(key=lambda x: x[0], reverse=True)
        seen = set()
        deduped = []
        for score, action, example in results:
            if action not in seen:
                seen.add(action)
                deduped.append((score, action, example))
                if len(deduped) >= top_k:
                    break
        return deduped

    @staticmethod
    def _cosine(a: Dict[str, float], b: Dict[str, float]) -> float:
        dot = sum(a.get(k, 0) * b.get(k, 0) for k in set(a) | set(b))
        mag_a = math.sqrt(sum(v ** 2 for v in a.values())) or 1e-10
        mag_b = math.sqrt(sum(v ** 2 for v in b.values())) or 1e-10
        return dot / (mag_a * mag_b)


# =========================================================
# TIER 2: LLM INTENT CLASSIFIER
# =========================================================

class LLMClassifier:
    """
    Uses local Ollama model for natural language understanding.
    Only called when TF-IDF confidence is too low.

    Optimizations:
      - Minimal prompt (fewer tokens = faster response)
      - temperature=0 (deterministic, no sampling overhead)
      - Structured JSON output for reliable parsing
      - Connection kept warm (Ollama keeps model loaded)
    """

    # Compact action descriptions for prompt
    ACTION_DESCRIPTIONS = {
        "EXIT": "exit/quit the agent",
        "WAKE": "wake/turn on screen",
        "BACK": "go back/previous screen",
        "HOME": "go to home screen",
        "CLOSE_ALL": "close all apps / clear recents",
        "CLOSE_APP": "close current app / close this app",
        "VOLUME_UP": "increase volume (not max)",
        "VOLUME_DOWN": "decrease volume",
        "VOLUME_MAX": "set volume to maximum/full",
        "VOLUME_MIN": "set volume to minimum/lowest",
        "VOLUME_MUTE": "mute/silence all sound",
        "VOLUME_UNMUTE": "unmute/restore sound",
        "MEDIA_PLAY": "play/resume music or media",
        "MEDIA_PAUSE": "pause music or media",
        "MEDIA_NEXT": "next/skip song or track",
        "MEDIA_PREVIOUS": "previous song or track",
        "SCROLL_DOWN": "scroll down on screen",
        "SCROLL_UP": "scroll up on screen",
        "OPEN_APP": "open/launch a specific app",
        "SEND_MESSAGE": "send message/chat/text someone",
        "SEARCH_IN_APP": "search for something",
        "TYPE_TEXT": "type some text",
        "TYPE_AND_SEND": "type text and press send",
        "VISION_QUERY": "click/tap a UI element by name",
        "SCREEN_INFO": "describe what's on screen",
        "SCREENSHOT": "take a screenshot",
        "BRIGHTNESS_UP": "increase screen brightness",
        "BRIGHTNESS_DOWN": "decrease screen brightness",
    }

    # ✅ CHANGED DEFAULT MODEL HERE
    def __init__(self, model: str = "qwen2.5:0.5b") -> None:
        self.model = model
        self.available = False
        self._check_availability()

    def _check_availability(self) -> None:
        try:
            import ollama
            # Verify model is actually available (not just import)
            models = ollama.list()
            model_names = [m.get('name', '') if isinstance(m, dict) else str(m)
                          for m in models.get('models', [])]
            if any(self.model in name for name in model_names):
                self.available = True
            else:
                self.available = False
                print(f"⚠️ LLM model '{self.model}' not found. Tier 2 disabled.")
                print(f"   Available: {', '.join(model_names[:5])}")
                print(f"   Fix: ollama pull {self.model}")
        except ImportError:
            self.available = False
        except Exception as e:
            # Ollama not running
            self.available = False
            print(f"⚠️ Ollama not reachable: {e}. Tier 2 disabled.")

    def classify(self, utterance: str) -> Optional[Dict]:
        """
        Classify utterance using LLM.

        Returns:
            {"action": "VOLUME_MAX", "params": {"amount": 15}} or None
        """
        if not self.available:
            return None

        try:
            import ollama

            # Build compact action list
            action_list = "\n".join(
                f"- {action}: {desc}"
                for action, desc in self.ACTION_DESCRIPTIONS.items()
            )

            prompt = f"""Classify this voice command into ONE action. Return ONLY valid JSON.

Actions:
{action_list}

Command: "{utterance}"

Return JSON: {{"action": "ACTION_NAME", "app": "app name or empty", "contact": "contact name or empty", "message": "message text or empty", "query": "search query or empty", "amount": number_or_0}}
JSON:"""

            response = ollama.chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                options={
                    "temperature": 0,
                    # ✅ CHANGED: shorter output for faster response
                    "num_predict": 60,
                },
            )

            content = response["message"]["content"].strip()

            # Parse JSON from response
            # Handle markdown code blocks
            content = re.sub(r'```json\s*', '', content)
            content = re.sub(r'```\s*', '', content)

            # Find JSON object
            m = re.search(r'\{[^}]+\}', content, re.DOTALL)
            if m:
                data = json.loads(m.group())
                if "action" in data and data["action"] in self.ACTION_DESCRIPTIONS:
                    return data

        except Exception as e:
            # Log the error so user knows Tier 2 failed
            print(f"  ⚠️ LLM classify failed: {e}")

        return None


# =========================================================
# TIER 3: SELF-LEARNING CACHE
# =========================================================

class LearningCache:
    """
    Persists LLM classifications so they become Tier 1 next time.

    Flow:
      1. "blast it" → TF-IDF unsure → LLM → VOLUME_MAX
      2. Cache: "blast it" → VOLUME_MAX
      3. Next time: TF-IDF finds "blast it" in cache → instant

    Also stores user-taught actions.
    """

    def __init__(self, path: str = "learned_actions.json") -> None:
        self.path = path
        self.cache: Dict[str, Dict] = {}  # phrase → {action, params, source}
        self._load()

    def _load(self) -> None:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r") as f:
                    self.cache = json.load(f)
            except Exception:
                self.cache = {}

    def _save(self) -> None:
        try:
            with open(self.path, "w") as f:
                json.dump(self.cache, f, indent=2)
        except Exception:
            pass

    def store(self, phrase: str, action: str, params: Dict,
              source: str = "llm", examples: Optional[List[str]] = None) -> None:
        """Store a classification result."""
        key = phrase.strip().lower()
        self.cache[key] = {
            "action": action,
            "params": params,
            "source": source,  # "llm", "user", "correction"
            "examples": examples or [],
            "timestamp": time.time(),
        }
        self._save()

    def lookup(self, phrase: str) -> Optional[Dict]:
        """Exact match lookup."""
        return self.cache.get(phrase.strip().lower())

    def forget(self, phrase: str) -> bool:
        key = phrase.strip().lower()
        if key in self.cache:
            del self.cache[key]
            self._save()
            return True
        return False

    def get_tfidf_entries(self) -> List[Tuple[str, str]]:
        """Get (action_key, phrase) pairs for TF-IDF indexing."""
        pairs = []
        for phrase, data in self.cache.items():
            action = data["action"]
            pairs.append((f"CACHED:{phrase}", phrase))
            for ex in data.get("examples", []):
                pairs.append((f"CACHED:{phrase}", ex))
        return pairs

    def list_all(self) -> None:
        if not self.cache:
            print("📚 No learned actions yet.")
            return
        print(f"📚 Learned Actions ({len(self.cache)}):")
        for phrase, data in sorted(self.cache.items()):
            src = data.get("source", "?")
            exs = data.get("examples", [])
            ex_str = f" (also: {', '.join(exs)})" if exs else ""
            print(f"  '{phrase}' → {data['action']} [{src}]{ex_str}")

    @property
    def count(self) -> int:
        return len(self.cache)


# =========================================================
# PARAMETER EXTRACTOR
# =========================================================

class ParamExtractor:
    """Extract structured parameters from natural language."""

    KEYEVENT_MAP = {
        "enter": "KEYCODE_ENTER", "tab": "KEYCODE_TAB",
        "escape": "KEYCODE_ESCAPE", "delete": "KEYCODE_DEL",
        "backspace": "KEYCODE_DEL", "space": "KEYCODE_SPACE",
    }

    def extract(self, action: str, utterance: str, llm_params: Optional[Dict] = None) -> Command:
        """
        Extract parameters for a classified action.
        llm_params: If available, use LLM-extracted params as hints.
        """
        raw = utterance.strip()
        t = raw.lower()

        # --- No-param commands ---
        if action in ("EXIT", "WAKE", "BACK", "HOME", "CLOSE_ALL", "CLOSE_APP",
                       "REINDEX_APPS", "TEACH_LAST", "LIST_MAPPINGS",
                       "MEDIA_PLAY", "MEDIA_PAUSE", "MEDIA_PLAY_PAUSE",
                       "MEDIA_NEXT", "MEDIA_PREVIOUS", "TAP_SEND",
                       "VOLUME_MUTE", "VOLUME_UNMUTE", "SCREENSHOT",
                       "VOLUME_MIN"):
            return Command(action=action)

        # --- Volume Max ---
        if action == "VOLUME_MAX":
            return Command(action="VOLUME_UP", amount=15)  # 15 steps = max

        # --- Volume ---
        if action in ("VOLUME_UP", "VOLUME_DOWN"):
            amt = 2
            if llm_params and llm_params.get("amount"):
                amt = int(llm_params["amount"])
            else:
                m = re.search(r'(\d+)', t)
                if m:
                    amt = int(m.group(1))
                elif any(w in t for w in ["more", "lot", "much"]):
                    amt = 5
            return Command(action=action, amount=amt)

        # --- Brightness ---
        if action in ("BRIGHTNESS_UP", "BRIGHTNESS_DOWN"):
            return Command(action=action, amount=1)

        # --- Scroll ---
        if action.startswith("SCROLL_"):
            direction = action.split("_")[1]
            amt = 1
            if "twice" in t or "two" in t:
                amt = 2
            elif "more" in t or "lot" in t:
                amt = 3
            m = re.search(r'(\d+)', t)
            if m:
                amt = int(m.group(1))
            return Command(action="SCROLL", direction=direction, amount=amt)

        # --- Swipe ---
        if action.startswith("SWIPE_"):
            direction = action.split("_")[1]
            return Command(action="SWIPE", direction=direction, amount=1)

        # --- Open App ---
        if action == "OPEN_APP":
            app = None
            if llm_params and llm_params.get("app"):
                app = llm_params["app"]
            else:
                app = self._after(t, ["open", "launch", "start", "go to",
                                       "switch to", "run", "take me to"])
                if app:
                    app = re.sub(r'\b(the|app|application|up|my)\b', '', app).strip()
            return Command(action="OPEN_APP", query=app or raw)

        # --- Find App ---
        if action == "FIND_APP":
            app = self._after(t, ["find", "search for app", "look for", "where is"])
            return Command(action="FIND_APP", query=app or raw)

        # --- Type ---
        if action == "TYPE_TEXT":
            text = self._after(t, ["type", "write", "enter", "input", "put"])
            return Command(action="TYPE_TEXT", text=text or raw)

        # --- Type and Send ---
        if action == "TYPE_AND_SEND":
            text = self._after(t, ["write", "type", "send"])
            if text:
                text = re.sub(r'\s+and\s+(send|hit send)\s*$', '', text, flags=re.I).strip()
                text = re.sub(r'\s+then\s+send\s*$', '', text, flags=re.I).strip()
            return Command(action="TYPE_AND_SEND", text=text or raw)

        # --- Type and Enter ---
        if action == "TYPE_AND_ENTER":
            text = self._after(t, ["type", "enter"])
            if text:
                text = re.sub(r'\s+and\s+(enter|press enter|search|submit)\s*$',
                              '', text, flags=re.I).strip()
            return Command(action="TYPE_AND_ENTER", text=text or raw)

        # --- Send Message ---
        if action == "SEND_MESSAGE":
            if llm_params:
                contact = llm_params.get("contact", "")
                message = llm_params.get("message", "")
                app = llm_params.get("app", "whatsapp")
                if contact:
                    return Command(action="SEND_MESSAGE", query=contact,
                                   text=message, package=app or "whatsapp")
            return self._extract_send(raw)

        # --- Search ---
        if action == "SEARCH_IN_APP":
            if llm_params:
                query = llm_params.get("query", "")
                app = llm_params.get("app", "")
                if query:
                    return Command(action="SEARCH_IN_APP", query=query, text=app)
            return self._extract_search(raw)

        # --- Open Content ---
        if action == "OPEN_CONTENT_IN_APP":
            return self._extract_content(raw)

        # --- Tap ---
        if action == "TAP":
            m = re.search(r'(\d{2,4})\s+(\d{2,4})', t)
            if m:
                return Command(action="TAP", x=int(m.group(1)), y=int(m.group(2)))
            return Command(action="TAP")

        # --- Vision ---
        if action == "VISION_QUERY":
            # FIRST: Check for "search for X on screen" / "find X and tap" patterns
            # "search for like on the screen and tap it" → "like"
            # "find the subscribe button and tap it" → "subscribe"
            m = re.search(
                r'(?:search\s+for|find|look\s+for)\s+(?:the\s+)?(.+?)(?:\s+on\s+(?:the\s+)?screen|\s+and\s+(?:tap|click|press|select)\b|\s*$)',
                t
            )
            if m:
                target = m.group(1).strip()
                target = re.sub(r'\s+button\s*$', '', target).strip()
                target = re.sub(r'\s+icon\s*$', '', target).strip()
            else:
                # THEN: Check for click/tap/press verbs
                target = self._after(t, ["click", "tap", "press", "select",
                                          "choose", "hit"])
                if target:
                    target = re.sub(r'^(on\s+)?(the\s+)?', '', target).strip()
                else:
                    # No action verb found — extract from natural speech
                    target = self._extract_ui_target(t)
            return Command(action="VISION_QUERY", query=target or raw)

        if action == "SCREEN_INFO":
            return Command(action="SCREEN_INFO", query=raw)

        if action == "FIND_VISUAL":
            target = self._after(t, ["find", "locate", "look for", "where is"])
            return Command(action="FIND_VISUAL", query=target or raw)

        # --- Teach ---
        if action == "TEACH_CUSTOM":
            rest = self._after(t, ["teach", "remember", "when i say"])
            if rest:
                parts = rest.split(None, 1)
                if len(parts) == 2:
                    return Command(action="TEACH_CUSTOM", query=parts[0], text=parts[1])
                return Command(action="TEACH_SHORTCUT", query=parts[0])
            return Command(action="TEACH_LAST")

        if action == "FORGET_MAPPING":
            target = self._after(t, ["forget", "unlearn", "remove mapping", "delete"])
            return Command(action="FORGET_MAPPING", query=target or raw)

        # --- Keyevent ---
        if action == "KEYEVENT":
            for name, code in self.KEYEVENT_MAP.items():
                if name in t:
                    return Command(action="KEYEVENT", query=code)
            return Command(action="KEYEVENT", query="KEYCODE_ENTER")

        return Command(action=action, query=raw)

    # ---- Message extraction ----

    def _extract_send(self, raw: str) -> Command:
        t = raw.lower().strip()

        # "send hello to poojitha on whatsapp"
        m = re.search(
            r'(?:send|tell)\s+(.+?)\s+to\s+(.+?)(?:\s+(?:on|in)\s+(.+))?$', t)
        if m:
            msg, contact, app = m.group(1), m.group(2), m.group(3)
            return Command(action="SEND_MESSAGE", query=contact.strip(),
                           text=msg.strip(), package=(app or "whatsapp").strip())

        # "text poojitha hello on/in whatsapp" or "text poojitha hello"
        m = re.search(
            r'(?:text|message)\s+(\S+)\s+(.+?)(?:\s+(?:on|in)\s+(\S+))?\s*$', t)
        if m:
            contact, msg, app = m.group(1), m.group(2), m.group(3)
            return Command(action="SEND_MESSAGE", query=contact.strip(),
                           text=msg.strip(), package=(app or "whatsapp").strip())

        # "message/text mom saying hello"
        m = re.search(r'(?:message|text|dm)\s+(\S+)\s+(?:saying|that)\s+(.+)$', t)
        if m:
            return Command(action="SEND_MESSAGE", query=m.group(1).strip(),
                           text=m.group(2).strip(), package="whatsapp")

        # "chat with mom" / "chat mom" / "message mom" / "text mom"
        m = re.search(
            r'(?:chat\s+with|chat|message|text|dm)\s+(.+?)(?:\s+(?:on|in)\s+(\S+))?\s*$', t)
        if m:
            contact = m.group(1).strip()
            app = m.group(2) or "whatsapp"
            return Command(action="SEND_MESSAGE", query=contact, text="",
                           package=app.strip())

        # "whatsapp poojitha good morning"
        m = re.search(r'(?:whatsapp|wa)\s+(\S+)\s*(.*)', t)
        if m:
            return Command(action="SEND_MESSAGE", query=m.group(1).strip(),
                           text=m.group(2).strip(), package="whatsapp")

        return Command(action="SEND_MESSAGE", query=raw, text="", package="whatsapp")

    def _extract_search(self, raw: str) -> Command:
        t = raw.lower().strip()
        m = re.search(r'(?:search|look up|find)\s+(.+?)\s+(?:on|in)\s+(.+)$', t)
        if m:
            return Command(action="SEARCH_IN_APP", query=m.group(1).strip(),
                           text=m.group(2).strip())
        m = re.search(r'(youtube|google)\s+(?:search\s+)?(.+)$', t)
        if m:
            return Command(action="SEARCH_IN_APP", query=m.group(2).strip(),
                           text=m.group(1).strip())
        m = re.search(r'(?:search|look up)\s+(?:for\s+)?(.+)$', t)
        if m:
            return Command(action="SEARCH_IN_APP", query=m.group(1).strip())
        return Command(action="SEARCH_IN_APP", query=raw)

    def _extract_content(self, raw: str) -> Command:
        t = raw.lower().strip()
        pos = 1
        for word, num in [("first", 1), ("second", 2), ("third", 3),
                          ("fourth", 4), ("fifth", 5)]:
            if word in t:
                pos = num
                break
        m = re.search(r'(?:play|open|watch)\s+(.+?)\s+(?:on|in)\s+(.+)$', t)
        if m:
            return Command(action="OPEN_CONTENT_IN_APP", query=m.group(1).strip(),
                           text=m.group(2).strip(), amount=pos)
        return Command(action="OPEN_CONTENT_IN_APP", query=raw, amount=pos)

    def _after(self, text: str, verbs: List[str]) -> Optional[str]:
        for verb in sorted(verbs, key=len, reverse=True):
            m = re.search(rf'\b{re.escape(verb)}\s+(.+)', text, re.I)
            if m:
                return m.group(1).strip()
        return None

    def _extract_ui_target(self, text: str) -> str:
        """
        Extract the clickable UI target from natural speech.
        
        "subscribe the youtube channel" → "subscribe"
        "like this video"               → "like"
        "share this"                    → "share"
        "open the menu"                 → "menu"
        "subscribe to this"             → "subscribe"
        "hit the like button"           → "like"
        
        Strategy: The first meaningful word is usually the UI element.
        Strip trailing context phrases like "the youtube channel", "this video", etc.
        """
        t = text.lower().strip()

        # Remove action verbs if present at start
        t = re.sub(r'^(click|tap|press|select|choose|hit|open)\s+(on\s+)?(the\s+)?', '', t).strip()

        # Remove trailing context phrases
        # "subscribe the youtube channel" → "subscribe"
        # "like this video" → "like"
        # "share this post" → "share"
        filler_patterns = [
            r'\s+the\s+youtube\s+channel.*$',
            r'\s+the\s+channel.*$',
            r'\s+this\s+youtube\s+channel.*$',
            r'\s+this\s+channel.*$',
            r'\s+to\s+(this|the)\s+(channel|video|page|post|account).*$',
            r'\s+to\s+this\s*$',
            r'\s+to\s+the\s*$',
            r'\s+to\s+it\s*$',
            r'\s+(this|the)\s+(video|post|page|image|photo|story|reel|comment|account).*$',
            r'\s+this\s*$',
            r'\s+it\s*$',
            r'\s+them\s*$',
            r'\s+button\s*$',
            r'\s+icon\s*$',
            r'\s+on\s+(this|the)\s+.*$',
        ]
        for pattern in filler_patterns:
            t = re.sub(pattern, '', t, flags=re.I).strip()

        # Clean trailing prepositions left over: "subscribe to" → "subscribe"
        t = re.sub(r'\s+to\s*$', '', t).strip()
        t = re.sub(r'\s+on\s*$', '', t).strip()
        t = re.sub(r'\s+in\s*$', '', t).strip()

        # If we still have multiple words, try to get just the key action word
        # "subscribe" is one word — good
        # "thumbs up" is two words — keep it (it's the UI element name)
        # But "subscribe channel youtube" should become "subscribe"
        words = t.split()
        if len(words) > 2:
            # Probably still has filler — take first 1-2 words
            t = " ".join(words[:2])

        return t if t else text


# =========================================================
# MAIN ENGINE: 3-TIER ARCHITECTURE
# =========================================================

# Confidence thresholds
TIER1_CONFIDENT = 0.65   # Above this: TF-IDF result is trusted
TIER1_UNCERTAIN = 0.35   # Below this: definitely need LLM
# Between 0.35-0.65: use TF-IDF but could be wrong


class IntentEngine:
    """
    3-Tier Natural Language Intent Engine.

    Tier 1: TF-IDF semantic match (~2ms) — handles 80%+ of commands
    Tier 2: LLM fallback (~300-800ms) — true NLU for ambiguous input
    Tier 3: Self-learning cache — LLM results become Tier 1 next time

    Usage:
        engine = IntentEngine()
        cmd = engine.understand("blast it")
        # First time:  Tier2 LLM → VOLUME_MAX → cached
        # Second time: Tier1 TF-IDF → instant
    """

    # ✅ CHANGED DEFAULT MODEL HERE
    def __init__(self, llm_model: str = "qwen2.5:0.5b") -> None:
        self.matcher = TFIDFMatcher()
        self.extractor = ParamExtractor()
        self.llm = LLMClassifier(model=llm_model)
        self.cache = LearningCache()
        self._build_index()

        # Stats for debugging
        self.stats = {"tier1": 0, "tier2": 0, "cache_hit": 0, "miss": 0}

    def _build_index(self) -> None:
        """Build TF-IDF index from knowledge base + cached learnings."""
        self.matcher = TFIDFMatcher()

        # Built-in examples
        for action, examples in ACTION_EXAMPLES.items():
            for example in examples:
                self.matcher.add_document(action, example)

        # Cached/learned entries (Tier 3)
        for action_key, text in self.cache.get_tfidf_entries():
            self.matcher.add_document(action_key, text)

        self.matcher.build()

    def rebuild_index(self) -> None:
        self._build_index()

    def understand(self, utterance: str, current_app: str = "") -> Optional[Command]:
        """
        Main entry point. Understands natural language → Command.

        Returns Command or None.
        """
        raw = utterance.strip()
        if not raw:
            return None

        t_start = time.perf_counter()

        # ============================
        # STEP 0: COMPOUND COMMANDS
        # ============================
        parts = split_compound(raw)
        if parts and len(parts) >= 2:
            valid = []
            for part in parts:
                sub = self._classify_single(part)
                if sub:
                    valid.append(part)
            if len(valid) >= 2:
                return Command(action="MULTI_STEP", query="|".join(valid))

        # ============================
        # STEP 1-3: SINGLE COMMAND
        # ============================
        cmd = self._classify_single(raw)

        elapsed = (time.perf_counter() - t_start) * 1000
        if cmd:
            # Debug timing (remove in production)
            pass  # print(f"  ⏱️ {elapsed:.1f}ms → {cmd.action}")

        return cmd

    def _classify_single(self, utterance: str) -> Optional[Command]:
        """Classify a single utterance through the 3-tier pipeline."""
        raw = utterance.strip()
        if not raw:
            return None
        t = raw.lower()

        # ============================
        # TIER 3 CHECK: Exact cache hit (instant)
        # ============================
        cached = self.cache.lookup(t)
        if cached:
            self.stats["cache_hit"] += 1
            action = cached["action"]
            params = cached.get("params", {})
            return self.extractor.extract(action, raw, llm_params=params)

        # ============================
        # TIER 0: REGEX FAST PATHS
        # ============================
        # These patterns are unambiguous but TF-IDF struggles with them
        # because the token overlap is poor.
        
        # "search for X on the screen and tap it" / "find X and tap it"
        # These are screen interaction, NOT app search
        m = re.search(
            r'(?:search\s+for|find|look\s+for)\s+(?:the\s+)?(.+?)(?:\s+on\s+(?:the\s+)?screen|\s+and\s+(?:tap|click|press|select)\b)',
            t
        )
        if m:
            target = m.group(1).strip()
            target = re.sub(r'\s+button\s*$', '', target).strip()
            target = re.sub(r'\s+icon\s*$', '', target).strip()
            return Command(action="VISION_QUERY", query=target)
        
        # Ordinals: "tap on 4th mail", "click the 3rd email", "select first video"
        # Any action verb + ordinal + item type → VISION_QUERY
        m = re.match(
            r'(?:tap|click|select|open|press|hit|choose)\s+'
            r'(?:on\s+)?(?:the\s+)?'
            r'(?:first|second|third|fourth|fifth|last|1st|2nd|3rd|4th|5th|\d+(?:st|nd|rd|th))\s+'
            r'(.+)',
            t
        )
        if m:
            target = re.sub(r'^(?:tap|click|select|open|press|hit|choose)\s+(?:on\s+)?(?:the\s+)?', '', t).strip()
            return Command(action="VISION_QUERY", query=target)
        
        # Bare ordinals: "4th mail", "first video", "second post"
        m = re.match(
            r'(?:the\s+)?'
            r'(first|second|third|fourth|fifth|last|1st|2nd|3rd|4th|5th|\d+(?:st|nd|rd|th))\s+'
            r'(\S+.*)',
            t
        )
        if m:
            target = f"{m.group(1)} {m.group(2)}"
            return Command(action="VISION_QUERY", query=target)

        # ============================
        # TIER 1: TF-IDF (fast path)
        # ============================
        matches = self.matcher.match(raw, top_k=3)

        if matches:
            best_score, best_action, _ = matches[0]

            # Handle cached TF-IDF entries
            if best_action.startswith("CACHED:"):
                phrase = best_action.split(":", 1)[1]
                cached_data = self.cache.lookup(phrase)
                if cached_data:
                    self.stats["cache_hit"] += 1
                    action = cached_data["action"]
                    params = cached_data.get("params", {})
                    return self.extractor.extract(action, raw, llm_params=params)

            # HIGH CONFIDENCE → trust TF-IDF
            if best_score >= TIER1_CONFIDENT:
                self.stats["tier1"] += 1
                return self.extractor.extract(best_action, raw)

            # MEDIUM CONFIDENCE → use TF-IDF but it might be wrong
            if best_score >= TIER1_UNCERTAIN:
                # Consult LLM for ALL uncertain cases (the whole point of Tier 2)
                if self.llm.available:
                    llm_result = self._tier2_classify(raw)
                    if llm_result:
                        return llm_result

                # LLM unavailable or failed — trust TF-IDF (better than nothing)
                self.stats["tier1"] += 1
                return self.extractor.extract(best_action, raw)

        # ============================
        # TIER 2: LLM (slow but smart)
        # ============================
        if self.llm.available:
            llm_result = self._tier2_classify(raw)
            if llm_result:
                return llm_result

        # ============================
        # FALLBACK: Best TF-IDF guess
        # ============================
        if matches and matches[0][0] > 0.15:
            self.stats["tier1"] += 1
            return self.extractor.extract(matches[0][1], raw)

        self.stats["miss"] += 1
        return None

    def _tier2_classify(self, utterance: str) -> Optional[Command]:
        """Tier 2: LLM classification with auto-caching."""
        llm_data = self.llm.classify(utterance)
        if not llm_data:
            return None

        action = llm_data["action"]
        self.stats["tier2"] += 1

        # TIER 3: Cache the result so it's instant next time
        self.cache.store(
            phrase=utterance.lower(),
            action=action,
            params={
                k: v for k, v in llm_data.items()
                if k != "action" and v
            },
            source="llm",
        )
        # Rebuild TF-IDF to include new cached entry
        self.rebuild_index()

        return self.extractor.extract(action, utterance, llm_params=llm_data)

    # =========================================================
    # USER TEACHING INTERFACE
    # =========================================================

    def teach_action(self, trigger: str, action: str, params: Dict,
                     examples: Optional[List[str]] = None) -> None:
        """Teach a custom action mapping."""
        self.cache.store(
            phrase=trigger.strip().lower(),
            action=action,
            params=params,
            source="user",
            examples=examples,
        )
        # Also cache examples
        if examples:
            for ex in examples:
                self.cache.store(
                    phrase=ex.strip().lower(),
                    action=action,
                    params=params,
                    source="user",
                )
        self.rebuild_index()
        print(f"✅ Learned: '{trigger}' → {action} {params}")

    def forget_action(self, trigger: str) -> bool:
        result = self.cache.forget(trigger)
        if result:
            self.rebuild_index()
        return result

    def list_learned(self) -> None:
        self.cache.list_all()

    def print_stats(self) -> None:
        total = sum(self.stats.values())
        if total == 0:
            print("📊 No commands processed yet.")
            return
        print(f"📊 Intent Engine Stats:")
        print(f"  Tier 1 (TF-IDF):   {self.stats['tier1']} ({self.stats['tier1']/total*100:.0f}%)")
        print(f"  Tier 2 (LLM):      {self.stats['tier2']} ({self.stats['tier2']/total*100:.0f}%)")
        print(f"  Tier 3 (Cached):   {self.stats['cache_hit']} ({self.stats['cache_hit']/total*100:.0f}%)")
        print(f"  Missed:            {self.stats['miss']} ({self.stats['miss']/total*100:.0f}%)")
        print(f"  Cached phrases:    {self.cache.count}")
