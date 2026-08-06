# =========================
# FILE: agent/intent_engine.py
# =========================
"""
Groq-first Intent Engine — Natural Language Understanding for Voice Agent.

Architecture:
  AUTHORITY — Groq LLM: understands natural / conversational commands.
              Always used when available (never skipped for TF-IDF confidence).

  CACHE — Exact repeats of prior LLM results are free (learning cache).

  FALLBACK — TF-IDF only when Groq is unavailable or fails.
             Also used as a cheap hint for speculative screen pre-fetch
             (does NOT choose the final action).

Voice Pipeline:
  [Whisper STT] → [Groq NLU] → [Execute]
                       ↕ parallel
                 [screen pre-fetch hint via TF-IDF]

Examples Groq should infer without hardcoded phrases:
  "my eyes are paining"      → BRIGHTNESS_DOWN
  "I am unable to hear anything" → VOLUME_UP
  "blast it"                 → VOLUME_MAX / VOLUME_UP
"""

import re
import math
import json
import os
import time
import threading
from typing import Optional, List, Dict, Tuple
from collections import Counter
from dotenv import load_dotenv
from agent.schema import Command

load_dotenv()


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
        "play", "resume", "resume music",
        "start playing", "continue playing", "unpause",
        "resume playback",
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
    "INSTALL_APP": [
        "install instagram", "download tiktok",
        "open playstore and install instagram",
        "install the whatsapp app",
        "download spotify from play store",
        "get telegram from the play store",
        "open play store and install netflix",
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

    # --- Device Features (WiFi, Bluetooth, Torch, etc.) ---
    "DEVICE_WIFI": [
        "enable wifi", "turn on wifi", "turn wifi on", "enable the wifi",
        "disable wifi", "turn off wifi", "turn wifi off", "disable the wifi",
        "toggle wifi", "wifi on", "wifi off", "switch wifi",
    ],
    "DEVICE_BLUETOOTH": [
        "enable bluetooth", "turn on bluetooth", "turn bluetooth on", "enable the bluetooth",
        "disable bluetooth", "turn off bluetooth", "turn bluetooth off", "disable the bluetooth",
        "toggle bluetooth", "bluetooth on", "bluetooth off", "switch bluetooth",
    ],
    "DEVICE_TORCH": [
        "enable torch", "turn on torch", "turn torch on", "enable the torch",
        "disable torch", "turn off torch", "turn torch off", "disable the torch",
        "toggle torch", "torch on", "torch off",
        "enable flashlight", "turn on flashlight", "turn on the light",
        "disable flashlight", "turn off flashlight", "turn off the light",
        "toggle flashlight", "flash on", "flash off", "light on", "light off",
        "enable flash", "turn on flash", "disable flash", "turn off flash",
    ],
    "DEVICE_CAMERA": [
        "launch camera", "open camera", "start camera", "activate camera",
        "open the camera", "launch the camera", "start the camera",
        "take a photo", "take photo", "capture photo",
        "take a picture", "capture picture",
        "launch video camera", "start video camera", "video camera",
        "record video", "start recording",
    ],
    "DEVICE_BRIGHTNESS": [
        "increase brightness", "increase screen brightness", "make it brighter",
        "brightness up", "brighter", "screen brighter", "brightness +10", "brightness plus 10",
        "decrease brightness", "decrease screen brightness", "make it dimmer",
        "brightness down", "dimmer", "screen dimmer", "dim screen", "brightness -10", "brightness minus 10",
        "set brightness to", "brightness to", "dim to", "bright to",
        "brightness 100", "brightness 200", "brightness 50", "brightness max",
        "brightness up please", "brighter please", "max brightness",
        "more brightness", "less brightness", "brighter please", "too bright", "too dark",
    ],
    "DEVICE_AUDIO": [
        "increase volume", "volume up", "louder", "make it louder", "turn up the volume",
        "volume +10", "volume plus 10", "crank it up", "increase sound", "boost volume",
        "decrease volume", "volume down", "quieter", "make it quieter", "turn down the volume",
        "volume -10", "volume minus 10", "reduce sound", "less loud", "not so loud",
        "set volume to", "volume to", "set volume at", "volume level",
        "volume 5", "volume 10", "volume 15", "volume max", "full volume",
        "mute", "silence", "turn off sound", "quiet mode", "mute device",
        "unmute", "restore sound", "turn on sound", "unsilence",
        "too loud", "too quiet", "volume is too high", "volume is too low",
        "blast it", "blast the volume", "loud as possible", "as loud as it goes",
    ],
    "DEVICE_LOCATION": [
        "enable location", "turn on location", "turn location on",
        "disable location", "turn off location", "turn location off",
        "toggle location", "location on", "location off",
        "enable gps", "turn on gps", "disable gps", "turn off gps",
        "enable positioning", "disable positioning",
    ],
    "DEVICE_AIRPLANE_MODE": [
        "enable airplane mode", "turn on airplane mode",
        "disable airplane mode", "turn off airplane mode",
        "toggle airplane mode", "airplane mode on", "airplane mode off",
    ],
    "DEVICE_VIBRATION": [
        "enable vibration", "turn on vibration",
        "disable vibration", "turn off vibration",
        "toggle vibration", "vibration on", "vibration off",
    ],
    "DEVICE_DO_NOT_DISTURB": [
        "enable do not disturb", "enable dnd", "turn on do not disturb",
        "disable do not disturb", "disable dnd", "turn off do not disturb",
        "toggle do not disturb", "do not disturb on", "do not disturb off",
        "dnd on", "dnd off", "silent mode", "enable silent mode",
    ],
    "DEVICE_BATTERY_SAVER": [
        "enable battery saver", "turn on battery saver", "turn battery saver on",
        "disable battery saver", "turn off battery saver", "turn battery saver off",
        "toggle battery saver", "battery saver on", "battery saver off",
    ],
    "DEVICE_MOBILE_DATA": [
        "enable mobile data", "turn on mobile data", "enable hotspot",
        "disable mobile data", "turn off mobile data", "disable hotspot",
        "toggle mobile data", "enable data", "disable data",
    ],
    "DEVICE_NFC": [
        "enable nfc", "turn on nfc", "enable nfc",
        "disable nfc", "turn off nfc",
        "toggle nfc", "nfc on", "nfc off",
    ],
    "DEVICE_AUTO_ROTATE": [
        "enable auto rotate", "turn on auto rotate",
        "disable auto rotate", "turn off auto rotate",
        "toggle auto rotate", "auto rotate on", "auto rotate off",
    ],
    "DEVICE_STATUS": [
        "device status", "show device status", "device info",
        "what is the status", "show me the status",
        "available features", "show available features",
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

def transcribe_audio(audio_path: str) -> Optional[str]:
    """
    Transcribe audio file to text using Groq whisper-large-v3-turbo endpoint.
    """
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        print("⚠️ GROQ_API_KEY not set. Groq Whisper STT disabled.")
        return None
    try:
        from groq import Groq
        client = Groq(api_key=api_key)
        with open(audio_path, "rb") as file:
            transcription = client.audio.transcriptions.create(
                file=(os.path.basename(audio_path), file.read()),
                model="whisper-large-v3-turbo",
                response_format="text"
            )
        return str(transcription).strip()
    except Exception as e:
        print(f"⚠️ Groq Whisper STT failed: {e}")
        return None


class LLMClassifier:
    """
    Uses Groq API (openai/gpt-oss-20b) for fast natural language understanding.
    Only called when TF-IDF confidence is too low.
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
        "SEARCH_IN_APP": "search for something inside an app (YouTube/Chrome/etc)",
        "INSTALL_APP": "install/download an app from the Play Store",
        "TYPE_TEXT": "type some text",
        "TYPE_AND_SEND": "type text and press send",
        "VISION_QUERY": "click/tap a UI element by name",
        "SCREEN_INFO": "describe what's on screen",
        "SCREENSHOT": "take a screenshot",
        "BRIGHTNESS_UP": "increase screen brightness",
        "BRIGHTNESS_DOWN": "decrease screen brightness",
    }

    def __init__(self, model: str = "openai/gpt-oss-20b") -> None:
        self.model = model
        self.client = None
        self.available = False
        self._check_availability()

    def _check_availability(self) -> None:
        api_key = os.environ.get("GROQ_API_KEY")
        if api_key:
            try:
                from groq import Groq
                self.client = Groq(api_key=api_key)
                self.available = True
            except Exception as e:
                self.available = False
                print(f"⚠️ Groq API client initialization failed: {e}. Tier 2 disabled.")
        else:
            self.available = False
            print("⚠️ GROQ_API_KEY not set. Tier 2 LLM disabled.")

    def classify(self, utterance: str) -> Optional[Dict]:
        """
        Classify utterance using Groq LLM with strict JSON output format.

        Returns:
            {"action": "VOLUME_MAX", "target": "volume", "params": {"amount": 15}} or None
        """
        if not self.available or not self.client:
            return None

        try:
            action_list = "\n".join(
                f"- {action}: {desc}"
                for action, desc in self.ACTION_DESCRIPTIONS.items()
            )

            system_prompt = (
                "You are a mobile voice assistant intent parser. Return ONLY valid JSON.\n"
                "Core principle: infer the USER'S GOAL from natural language — including "
                "complaints, symptoms, and indirect phrasing. Do NOT require exact command words.\n"
                "Rules:\n"
                "1. 'app' MUST ONLY be set for an explicit third-party app name "
                "(YouTube, Spotify, WhatsApp, Chrome, etc.). Never set 'app' to generic words "
                "like 'music', 'video', or search keywords.\n"
                "2. 'can you play <X>' / 'play <X>' where X is a song, artist, genre, or topic "
                "→ SEARCH_IN_APP with query=X. MEDIA_PLAY only resumes playback with no target.\n"
                "3. Infer device adjustments from how the user feels or what they need:\n"
                "   - Eye pain / strain / 'too bright' / hard to look at screen → BRIGHTNESS_DOWN\n"
                "   - Screen too dark / can't see → BRIGHTNESS_UP\n"
                "   - Can't hear / unable to hear / too quiet → VOLUME_UP\n"
                "   - Too loud / ears hurting / reduce sound → VOLUME_DOWN\n"
                "   - Silence / mute / be quiet → VOLUME_MUTE\n"
                "4. Prefer the action that best fixes the user's problem. Never leave "
                "conversational requests unclassified when a device action clearly applies.\n"
                "5. UI taps ('click subscribe', 'tap the red shirt') → VISION_QUERY with target text.\n"
                "6. Install/download an app ('install Instagram', 'open playstore and install TikTok') "
                "→ INSTALL_APP with query=app name."
            )

            prompt = f"""Classify this voice command into ONE action.

Actions:
{action_list}

Command: "{utterance}"

Return JSON matching this exact structure:
{{
  "action": "ACTION_NAME",
  "target": "target element or empty",
  "params": {{}},
  "app": "explicit app name or empty",
  "contact": "contact name or empty",
  "message": "message text or empty",
  "query": "search query or empty",
  "amount": 0
}}"""

            # Ask for JSON up front. Without this the model routinely returned
            # empty content, and the old retry (which added json_object mode on
            # a second call) cost another round trip and often 400'd anyway.
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                temperature=0,
                max_tokens=400,
                response_format={"type": "json_object"},
            )

            content = (response.choices[0].message.content or "").strip()
            if not content:
                content = self._salvage_content(response)

            content = re.sub(r'```json\s*', '', content)
            content = re.sub(r'```\s*', '', content)

            m = re.search(r'\{.*\}', content, re.DOTALL)
            if m:
                data = json.loads(m.group())
                if "action" in data and data["action"] in self.ACTION_DESCRIPTIONS:
                    if "target" not in data:
                        data["target"] = data.get("app") or data.get("contact") or ""
                    if "params" not in data or not isinstance(data["params"], dict):
                        data["params"] = {
                            "app": data.get("app", ""),
                            "contact": data.get("contact", ""),
                            "message": data.get("message", ""),
                            "query": data.get("query", ""),
                            "amount": data.get("amount", 0),
                        }
                    return data

        except Exception as e:
            print(f"  ⚠️ Groq LLM classify failed: {e}")

        return None

    @staticmethod
    def _salvage_content(response) -> str:
        """Pull JSON out of reasoning/tool fields when content comes back empty."""
        try:
            msg = response.choices[0].message
        except Exception:
            return ""
        for attr in ("reasoning", "reasoning_content"):
            val = getattr(msg, attr, None)
            if val and "{" in val:
                return val.strip()
        try:
            for call in getattr(msg, "tool_calls", None) or []:
                args = getattr(getattr(call, "function", None), "arguments", "")
                if args and "{" in args:
                    return args.strip()
        except Exception:
            pass
        return ""



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

        # --- Absolute volume (percent) ---
        if action in ("VOLUME_SET", "DEVICE_AUDIO"):
            # Prefer absolute "to N" / "at N" / "volume 50"
            m = re.search(
                r"(?:volume|sound|audio).{0,20}?(?:to|at|=|:)\s*(\d{1,3})\s*%?",
                t,
            )
            if not m:
                m = re.search(r"(?:set|put|make).{0,20}?(?:volume|sound).{0,12}?(\d{1,3})\s*%?", t)
            if not m:
                m = re.search(r"\b(?:volume|sound)\s+(\d{1,3})\s*%?\b", t)
            if m:
                return Command(action="VOLUME_SET", amount=int(m.group(1)))
            if any(w in t for w in ("mute", "silence", "silent")):
                return Command(action="VOLUME_MUTE")
            if any(w in t for w in ("unmute", "unsilence")):
                return Command(action="VOLUME_UNMUTE")
            if any(w in t for w in ("max", "full", "loudest", "blast")):
                return Command(action="VOLUME_MAX")
            if any(w in t for w in ("down", "lower", "quieter", "decrease", "reduce", "softer")):
                return Command(action="VOLUME_DOWN", amount=2)
            if any(w in t for w in ("up", "louder", "increase", "raise", "boost")):
                return Command(action="VOLUME_UP", amount=2)
            if action == "DEVICE_AUDIO":
                return Command(action="VOLUME_UP", amount=2)

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
            if not text:
                text = raw
            text = re.sub(r'^(?:type|write|enter|input|put)\s+', '', text, flags=re.I).strip()
            return Command(action="TYPE_TEXT", text=text)

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

        # --- Install from Play Store ---
        if action == "INSTALL_APP":
            if llm_params:
                query = llm_params.get("query") or llm_params.get("target") or ""
                # The LLM often echoes the verb back ("install snapchat")
                query = IntentEngine._clean_app_name(query)
                if query:
                    return Command(action="INSTALL_APP", query=query)
            m = re.search(
                r'(?:install|download|get)\s+(?:the\s+)?(.+?)(?:\s+app)?(?:\s+from\s+.+)?$',
                t, re.I,
            )
            if m:
                return Command(action="INSTALL_APP", query=m.group(1).strip())
            return Command(action="INSTALL_APP", query=raw)

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

# Confidence thresholds — used only for prefetch hints / offline fallback.
# When Groq is available it is ALWAYS the authority for the final action.
TIER1_CONFIDENT = 0.65
TIER1_UNCERTAIN = 0.35


class IntentEngine:
    """
    Natural-language intent engine (Groq-first).

    When Groq is available:
      - Exact learning-cache hits are free repeats of prior LLM results
      - Everything else is classified by Groq (true NLU, no phrase hardcoding)
      - TF-IDF is only used as a cheap offline fallback / prefetch hint

    When Groq is unavailable:
      - TF-IDF + learning cache provide best-effort offline control
    """

    def __init__(self, llm_model: str = "openai/gpt-oss-20b") -> None:
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
        """
        raw = utterance.strip()
        if not raw:
            return None

        # Fast structural workflows (no Groq) — biggest latency win
        structural = self._structural_simple_command(raw)
        if structural:
            return structural
        structural = self._structural_chrome_action(raw)
        if structural:
            return structural
        structural = self._structural_screen_info(raw)
        if structural:
            return structural
        structural = self._structural_take_photo(raw)
        if structural:
            return structural
        structural = self._structural_install_command(raw)
        if structural:
            return structural
        structural = self._structural_search_command(raw)
        if structural:
            return structural
        structural = self._structural_motion_command(raw)
        if structural:
            return structural

        # Compound: "open chrome and search for X" already handled above;
        # remaining compounds still split, but classify parts WITHOUT Groq first
        parts = split_compound(raw)
        if parts and len(parts) >= 2:
            valid = []
            for part in parts:
                # Prefer structural / cache / TF-IDF for sub-steps to avoid N Groq calls
                sub = self._classify_single(part, allow_llm=False)
                if not sub:
                    sub = self._classify_single(part, allow_llm=True)
                if sub:
                    valid.append(part)
            if len(valid) >= 2:
                return Command(action="MULTI_STEP", query="|".join(valid))

        return self._classify_single(raw, allow_llm=True)

    def _structural_screen_info(self, raw: str) -> Optional[Command]:
        """Instant parse for 'what do you see on screen?' style questions."""
        tl = raw.lower().strip()
        cues = (
            "what do you see", "what's on screen", "whats on screen",
            "what is on screen", "describe screen", "describe the screen",
            "describe what is on", "read the screen", "what's on the screen",
            "what can you see", "what do you see on screen",
        )
        if any(c in tl for c in cues):
            print("  ⚡ Fast-path SCREEN_INFO")
            return Command(action="SCREEN_INFO", query=raw)
        return None

    def _structural_take_photo(self, raw: str) -> Optional[Command]:
        """
        Instant parse for shutter / capture commands.

        'click a picture', 'take a photo', 'capture' → TAKE_PHOTO
        (not OPEN_APP camera, not VISION_QUERY for the word 'picture').
        """
        tl = raw.lower().strip()
        cues = (
            "take a photo", "take photo", "take a picture", "take picture",
            "click a photo", "click photo", "click a picture", "click picture",
            "capture photo", "capture picture", "press shutter", "hit shutter",
            "tap shutter", "snap a photo", "snap photo", "take a phott",
        )
        if any(c in tl for c in cues) or tl in {"shutter", "capture", "snap"}:
            print("  ⚡ Fast-path TAKE_PHOTO")
            return Command(action="TAKE_PHOTO", query=raw)
        return None

    def _structural_install_command(self, raw: str) -> Optional[Command]:
        """
        Instant parse for Play Store install workflows.

        Examples:
          open playstore and install instagram
          install instagram from the play store
          download tiktok
          install the instagram app
        """
        t = raw.strip()
        tl = t.lower()

        # open play store and install/download <app>
        m = re.match(
            r'^(?:please\s+)?(?:can\s+you\s+)?'
            r'open\s+(?:the\s+)?(play\s*store|playstore|google\s*play)\s+'
            r'(?:and\s+|then\s+)?'
            r'(?:install|download|get)\s+(?:the\s+)?(.+?)(?:\s+app)?\s*$',
            tl, re.I,
        )
        if m:
            app = m.group(2).strip(" .")
            # Preserve casing from original
            m2 = re.search(r'(?:install|download|get)\s+(?:the\s+)?(.+?)(?:\s+app)?\s*$', t, re.I)
            if m2:
                app = m2.group(1).strip(" .")
            if app:
                print(f"  ⚡ Fast-path INSTALL_APP query={app!r}")
                return Command(action="INSTALL_APP", query=app)

        # install/download <app> (from play store)?
        m = re.match(
            r'^(?:please\s+)?(?:can\s+you\s+)?'
            r'(?:install|download|get)\s+(?:the\s+)?(.+?)'
            r'(?:\s+(?:app|application))?'
            r'(?:\s+from\s+(?:the\s+)?(?:play\s*store|playstore|google\s*play))?\s*$',
            tl, re.I,
        )
        if m:
            app = m.group(1).strip(" .")
            m2 = re.match(
                r'^(?:please\s+)?(?:can\s+you\s+)?'
                r'(?:install|download|get)\s+(?:the\s+)?(.+?)'
                r'(?:\s+(?:app|application))?'
                r'(?:\s+from\s+(?:the\s+)?(?:play\s*store|playstore|google\s*play))?\s*$',
                t, re.I,
            )
            if m2:
                app = m2.group(1).strip(" .")
            app = self._clean_app_name(app)
            # Avoid swallowing unrelated "get me volume up" etc.
            bad = {"volume", "brightness", "wifi", "bluetooth", "home", "back"}
            if app and app.lower() not in bad and len(app) > 1:
                print(f"  ⚡ Fast-path INSTALL_APP query={app!r}")
                return Command(action="INSTALL_APP", query=app)

        return None

    @staticmethod
    def _clean_app_name(name: str) -> str:
        """
        Strip leftover verbs/filler from an extracted app name.

        The extraction regexes only remove one leading verb, so a stuttered or
        mis-transcribed utterance ("install install snapchat") left the verb in
        the query and the Play Store searched for the wrong thing.
        """
        if not name:
            return ""
        cleaned = name.strip(" .")
        # Repeatedly peel leading verbs and filler words
        pattern = re.compile(
            r'^(?:please|can\s+you|could\s+you|install|download|get|me|the|a|an|'
            r'app|application|for)\s+',
            re.I,
        )
        while True:
            new = pattern.sub('', cleaned).strip()
            if new == cleaned or not new:
                break
            cleaned = new
        cleaned = re.sub(
            r'\s+(?:app|application)$', '', cleaned, flags=re.I
        ).strip()
        cleaned = re.sub(
            r'\s+from\s+(?:the\s+)?(?:play\s*store|playstore|google\s*play)$',
            '', cleaned, flags=re.I,
        ).strip()
        return cleaned

    def _structural_search_command(self, raw: str) -> Optional[Command]:
        """
        Instant parse for common search workflows.
        Avoids Groq + MULTI_STEP + double classify.

        Examples:
          open chrome and search for AI engineers
          search for AI engineers on google
          google AI engineers
          search AI engineers on youtube
        """
        t = raw.strip()
        tl = t.lower()

        # open <app> and search for <query>
        m = re.match(
            r'^(?:please\s+)?(?:can\s+you\s+)?'
            r'open\s+(\w[\w\s]*?)\s+(?:and\s+)?(?:then\s+)?'
            r'(?:search|look\s+up|find)\s+(?:for\s+)?(.+)$',
            tl, re.I,
        )
        if m:
            app = m.group(1).strip()
            query = m.group(2).strip()
            # Preserve original query casing from raw when possible
            q_match = re.search(r'(?:search|look\s+up|find)\s+(?:for\s+)?(.+)$', t, re.I)
            if q_match:
                query = q_match.group(1).strip()
            if app and query:
                print(f"  ⚡ Fast-path SEARCH_IN_APP app={app!r} query={query!r}")
                return Command(action="SEARCH_IN_APP", query=query, text=app)

        # search for <query> on <app>
        m = re.match(
            r'^(?:please\s+)?(?:can\s+you\s+)?'
            r'(?:search|look\s+up|find)\s+(?:for\s+)?(.+?)\s+on\s+(\w[\w\s]*)$',
            tl, re.I,
        )
        if m:
            query, app = m.group(1).strip(), m.group(2).strip()
            q_match = re.search(r'(?:search|look\s+up|find)\s+(?:for\s+)?(.+?)\s+on\s+', t, re.I)
            if q_match:
                query = q_match.group(1).strip()
            if app.lower() in {"google", "chrome", "youtube", "yt", "safari", "bing"}:
                print(f"  ⚡ Fast-path SEARCH_IN_APP app={app!r} query={query!r}")
                return Command(action="SEARCH_IN_APP", query=query, text=app)

        # google <query>  /  youtube <query>
        m = re.match(r'^(?:please\s+)?(google|youtube|chrome)\s+(.+)$', tl, re.I)
        if m:
            app, query = m.group(1).strip(), m.group(2).strip()
            q_match = re.match(r'^(?:please\s+)?(?:google|youtube|chrome)\s+(.+)$', t, re.I)
            if q_match:
                query = q_match.group(1).strip()
            if query and query.lower() not in {"search", "app", "it"}:
                print(f"  ⚡ Fast-path SEARCH_IN_APP app={app!r} query={query!r}")
                return Command(action="SEARCH_IN_APP", query=query, text=app)

        return None

    # Unambiguous one-liners. These used to cost a full Groq round trip (~800ms)
    # even though they map to a single fixed action.
    _SIMPLE_COMMANDS = {
        "BACK": ("back", "go back", "previous screen", "navigate back"),
        "HOME": ("home", "go home", "home screen", "go to home"),
        "CLOSE_APP": ("close app", "close the app", "close this app", "quit app"),
        "CLOSE_ALL": ("close all", "close all apps", "clear all", "close everything"),
        "WAKE": ("wake", "wake up", "wake the device", "turn on screen"),
        "EXIT": ("exit", "quit", "stop", "bye", "goodbye"),
        "SCREENSHOT": ("screenshot", "take a screenshot", "capture screen",
                       "take screenshot", "screen shot"),
        "MEDIA_PLAY": ("play", "resume", "play it", "start playing"),
        "MEDIA_PAUSE": ("pause", "pause it", "stop playing"),
        "MEDIA_NEXT": ("next", "next song", "next track", "skip", "skip song",
                       "next video", "skip track"),
        # Distinct from MEDIA_NEXT: skipping an ad taps the on-screen "Skip ad"
        # button, whereas MEDIA_NEXT would jump to the next video entirely.
        "SKIP_AD": ("skip ad", "skip the ad", "skip ads", "skip the ads",
                    "skip this ad", "skip advertisement", "skip the advertisement",
                    "skip add", "skip the add", "skip adds", "skip the adds",
                    "skip commercial", "close ad", "dismiss ad"),
        "MEDIA_PREVIOUS": ("previous", "previous song", "previous track",
                           "last song", "go back a song"),
        "VOLUME_MUTE": ("mute", "silence", "be quiet", "mute it"),
        "VOLUME_UNMUTE": ("unmute", "unmute it", "restore sound"),
        "VOLUME_MAX": ("max volume", "full volume", "volume max", "loudest",
                       "blast it", "full blast"),
        "VOLUME_MIN": ("minimum volume", "lowest volume", "volume minimum"),
        "TAP_SEND": ("send", "send it", "hit send", "press send"),
        "LIST_MAPPINGS": ("list mappings", "show mappings", "list workflows"),
        "REINDEX_APPS": ("reindex apps", "refresh apps", "rescan apps"),
    }

    _SIMPLE_LOOKUP = None

    def _structural_simple_command(self, utterance: str) -> Optional[Command]:
        """Exact-phrase match for unambiguous commands — no LLM, no TF-IDF."""
        cls = type(self)
        if cls._SIMPLE_LOOKUP is None:
            table = {}
            for action, phrases in cls._SIMPLE_COMMANDS.items():
                for p in phrases:
                    table[p] = action
            cls._SIMPLE_LOOKUP = table

        t = utterance.lower().strip().rstrip("!.?")
        t = re.sub(r'^(?:please|can you|could you|hey|ok|okay)\s+', '', t).strip()
        t = re.sub(r'\s+please$', '', t).strip()

        action = cls._SIMPLE_LOOKUP.get(t)
        if not action:
            return None
        print(f"  ⚡ Fast-path {action}")
        return self.extractor.extract(action, utterance)

    # Toggle buttons the user names directly. These resolve from the UI tree in
    # ScreenController, so routing them through Groq only added latency.
    _CHROME_ACTIONS = (
        "unsubscribe", "subscribe", "unlike", "like", "undislike", "dislike",
        "unfollow", "follow", "share", "save", "download",
    )

    def _structural_chrome_action(self, utterance: str,
                                  quiet: bool = False) -> Optional[Command]:
        """Instant parse for 'like the video' / 'subscribe to the channel'."""
        t = utterance.lower().strip().rstrip("!.?")
        t = re.sub(r'^(?:please|can you|could you|hey|ok|okay)\s+', '', t).strip()
        t = re.sub(r'^(?:go\s+ahead\s+and\s+)?(?:click|tap|press|hit|select)\s+', '', t).strip()
        t = re.sub(r'^(?:on|the)\s+', '', t).strip()

        for action in self._CHROME_ACTIONS:
            m = re.match(
                rf'^{action}\b(?:\s+(?:to|on|this|that|the|it|from))*'
                r'(?:\s+(?:video|channel|post|reel|creator|page|clip|short))?$',
                t,
            )
            if m:
                if not quiet:
                    print(f"  ⚡ Fast-path {action.upper()}")
                return Command(action="VISION_QUERY", query=action)
        return None

    def _structural_motion_command(self, utterance: str) -> Optional[Command]:
        """Scroll / swipe / volume-step / app-launch verbs with a fixed shape."""
        t = utterance.lower().strip().rstrip("!.?")
        t = re.sub(r'^(?:please|can you|could you)\s+', '', t).strip()

        m = re.match(
            r'^(?:scroll|swipe)\s+(up|down|left|right)(?:\s+(?:by\s+)?(\d+))?(?:\s+times?)?$',
            t,
        )
        if m:
            direction = m.group(1).upper()
            amount = int(m.group(2)) if m.group(2) else 1
            verb = "SCROLL" if t.startswith("scroll") else "SWIPE"
            print(f"  ⚡ Fast-path {verb} {direction}")
            return Command(action=verb, direction=direction, amount=amount)

        m = re.match(r'^(?:volume|sound)\s+(up|down)$|^(?:turn\s+)?(up|down)\s+the\s+(?:volume|sound)$', t)
        if m:
            direction = (m.group(1) or m.group(2)).upper()
            action = "VOLUME_UP" if direction == "UP" else "VOLUME_DOWN"
            print(f"  ⚡ Fast-path {action}")
            return Command(action=action, amount=2)

        # launch/start/go to <app> — "open X" is handled separately below
        m = re.match(r'^(?:launch|start|go\s+to|switch\s+to|take\s+me\s+to)\s+(.+)$', t)
        if m:
            app = re.sub(r'\b(the|app|application)\b', '', m.group(1)).strip()
            if app and "search" not in app and len(app) < 40:
                print(f"  ⚡ Fast-path OPEN_APP query={app!r}")
                return Command(action="OPEN_APP", query=app)

        return None

    def _classify_single(self, utterance: str, allow_llm: bool = True) -> Optional[Command]:
        """
        Classify one utterance.

        Authority order:
          1. Exact learning-cache hit
          2. Structural search (already handled in understand for full utterance)
          3. Groq LLM (when allow_llm)
          4. TF-IDF offline fallback
        """
        raw = utterance.strip()
        if not raw:
            return None

        cached = self.cache.lookup(raw.lower())
        if cached:
            self.stats["cache_hit"] += 1
            action = cached["action"]
            params = cached.get("params", {})
            return self.extractor.extract(action, raw, llm_params=params)

        # Cheap structural for sub-steps too
        structural = self._structural_simple_command(raw)
        if structural:
            return structural
        structural = self._structural_chrome_action(raw)
        if structural:
            return structural
        structural = self._structural_motion_command(raw)
        if structural:
            return structural
        structural = self._structural_screen_info(raw)
        if structural:
            return structural
        structural = self._structural_take_photo(raw)
        if structural:
            return structural
        structural = self._structural_install_command(raw)
        if structural:
            return structural
        structural = self._structural_search_command(raw)
        if structural:
            return structural

        # Simple OPEN_APP without Groq
        m = re.match(r'^(?:please\s+)?(?:can\s+you\s+)?open\s+(.+)$', raw.strip(), re.I)
        if m:
            app = m.group(1).strip()
            if app and "search" not in app.lower():
                return Command(action="OPEN_APP", query=app)

        if allow_llm and self.llm.available:
            llm_result = self._tier2_classify(raw)
            if llm_result:
                return llm_result

        return self._tfidf_fallback(raw)

    def _tfidf_fallback(self, raw: str) -> Optional[Command]:
        """Best-effort classification when Groq is unavailable or failed."""
        matches = self.matcher.match(raw, top_k=3)
        if not matches:
            self.stats["miss"] += 1
            return None

        best_score, best_action, _ = matches[0]

        if best_action.startswith("CACHED:"):
            phrase = best_action.split(":", 1)[1]
            cached_data = self.cache.lookup(phrase)
            if cached_data:
                self.stats["cache_hit"] += 1
                return self.extractor.extract(
                    cached_data["action"], raw, llm_params=cached_data.get("params", {})
                )

        if best_score > 0.15:
            self.stats["tier1"] += 1
            return self.extractor.extract(best_action, raw)

        self.stats["miss"] += 1
        return None

    def prefetch_hint(self, utterance: str) -> Tuple[bool, bool]:
        """
        Cheap TF-IDF-only hint for speculative screen pre-fetch.
        Does NOT decide the final action — Groq does.

        Returns:
            (needs_screen, needs_screenshot)
        """
        raw = utterance.strip()
        if not raw:
            return False, False

        raw_lower = raw.lower()
        visual_cues = any(w in raw_lower for w in [
            "click", "tap", "select", "find", "look", "see", "show", "press",
            "hit", "choose", "button", "icon", "image", "photo", "picture",
            "on screen", "subscribe", "like", "share",
        ])

        # Named chrome buttons ("like the video", "subscribe") resolve straight
        # from the UI tree and return before vision is ever consulted, so the
        # ~1.6s speculative screenshot was pure added latency on every one.
        if self._structural_chrome_action(raw, quiet=True) is not None:
            return True, False

        matches = self.matcher.match(raw, top_k=1)
        action = matches[0][1] if matches and matches[0][0] >= TIER1_UNCERTAIN else ""
        if action.startswith("CACHED:"):
            phrase = action.split(":", 1)[1]
            cached = self.cache.lookup(phrase)
            action = (cached or {}).get("action", "")

        screen_actions = {
            "VISION_QUERY", "FIND_VISUAL", "SCREEN_INFO", "SEARCH_IN_APP",
            "INSTALL_APP",
            "SEND_MESSAGE", "TYPE_AND_SEND", "TAP_SEND", "APP_ACTION",
            "OPEN_CONTENT_IN_APP",
        }
        needs_screen = visual_cues or action in screen_actions or not action
        needs_screenshot = visual_cues or action in {
            "VISION_QUERY", "FIND_VISUAL", "SCREEN_INFO",
        }
        return needs_screen, needs_screenshot

    def _tier2_classify(self, utterance: str) -> Optional[Command]:
        """Groq LLM classification with auto-caching of successful results."""
        llm_data = self.llm.classify(utterance)
        if not llm_data:
            return None

        action = llm_data["action"]
        self.stats["tier2"] += 1

        # Cache so the exact same phrase is free next time
        self.cache.store(
            phrase=utterance.lower(),
            action=action,
            params={
                k: v for k, v in llm_data.items()
                if k != "action" and v
            },
            source="llm",
        )
        self.rebuild_index()

        return self.extractor.extract(action, utterance, llm_params=llm_data)

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
        print(f"  Cache hits:        {self.stats['cache_hit']} ({self.stats['cache_hit']/total*100:.0f}%)")
        print(f"  Groq NLU:          {self.stats['tier2']} ({self.stats['tier2']/total*100:.0f}%)")
        print(f"  TF-IDF fallback:   {self.stats['tier1']} ({self.stats['tier1']/total*100:.0f}%)")
        print(f"  Missed:            {self.stats['miss']} ({self.stats['miss']/total*100:.0f}%)")
        print(f"  Cached phrases:    {self.cache.count}")
