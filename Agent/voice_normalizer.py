# =========================
# FILE: agent/voice_normalizer.py
# =========================
"""
Cleans a raw speech transcript into something the intent engine can classify.

Speech reaches the agent with three problems typing never has:

  1. Homophones. Whisper hears "school down" for "scroll down", "blue tooth"
     for "bluetooth", "turn of" for "turn off". The intent engine is good at
     paraphrase but it cannot recover a word that was never transcribed.
  2. Mispronounced or accented app names. "sportify", "insta gram",
     "chad gpt", "linkden". These are fixed against the labels of the apps
     actually installed on the tablet, so correction follows the device rather
     than a hardcoded list.
  3. Disfluency and silence artifacts. Filler words, stutters, and Whisper's
     habit of emitting "Thanks for watching!" when handed near-silence. Acting
     on those would tap real buttons on a real device, so anything that isn't
     plausibly a command is rejected outright.

Corrections are deliberately context-scoped. Rewriting every "school" to
"scroll" would corrupt "search for school on YouTube", so the risky rules only
fire next to the words that make them unambiguous — a direction, an app verb,
a tap verb.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Callable, Dict, List, Optional, Sequence, Tuple


@dataclass
class NormalizedSpeech:
    raw: str
    text: str
    corrections: List[str] = field(default_factory=list)
    accepted: bool = True
    reason: str = ""

    @property
    def changed(self) -> bool:
        return self.accepted and self.text.lower() != self.raw.strip().lower()


# ---------------------------------------------------------------------------
# Rejection: transcripts that are noise rather than commands
# ---------------------------------------------------------------------------

# Whisper's stock output when fed silence, music, or room tone.
HALLUCINATIONS = [
    re.compile(p, re.I) for p in (
        r"thanks?(?: you)? for watching.*",
        r"thank you\.?",
        r"thanks\.?",
        r"please subscribe.*",
        r"(?:english )?subtitles?(?: by| provided by| amara).*",
        r"transcription by.*",
        r"amara\.org.*",
        r"www\..*",
        r"\[.*\]",                 # [BLANK_AUDIO], [MUSIC]
        r"\(.*\)",                 # (upbeat music)
        r"[\u266a\u266b\u2669]+.*",  # musical notes
        r"bye(?:[ -]bye)?\.?",
        r"[.\u2026!?,\s]*",        # bare punctuation
    )
]

# Single words that are almost always room noise or backchannel, not commands.
NOISE_TOKENS = {
    "you", "the", "a", "an", "and", "so", "well", "oh", "ah", "uh", "um", "erm",
    "hmm", "mm", "mhm", "huh", "eh", "yeah", "yep", "yes", "no", "nope", "ok",
    "okay", "right", "hi", "hey", "hello", "what", "who", "me", "i", "it",
    "this", "that", "is", "was", "to", "of", "in", "on", "for", "he", "she",
}

# Short words that ARE valid commands, so they survive the noise filter.
SHORT_COMMANDS = {
    "back", "home", "close", "exit", "quit", "stop", "play", "pause", "next",
    "previous", "up", "down", "left", "wake", "mute", "unmute", "louder",
    "quieter", "brighter", "darker", "screenshot", "scroll", "swipe", "refresh",
    "enter", "send", "search", "open", "top", "bottom", "like", "subscribe",
    "settings", "wifi", "bluetooth", "torch", "flashlight", "reload",
}

# Disfluencies removed anywhere in the utterance.
FILLERS = [
    re.compile(r"\b(?:um+|uh+|erm+|hmm+|mm-?hmm|uhh+|ahh+)\b[,.]?", re.I),
    re.compile(r"\b(?:you know|i mean|kind of|sort of)\b[,.]?", re.I),
]

# Politeness and wake words, only where they wrap the command.
LEADING_NOISE = re.compile(
    r"^(?:(?:hey|hi|hello|ok|okay|alright|so|well|now|and|um|uh|erm|please|"
    r"could you|would you)[,\s]+)+",
    re.I,
)
WAKE_WORDS = re.compile(
    r"^(?:hey\s+)?(?:agent|assistant|computer|tablet|jarvis)[,\s]+", re.I
)
TRAILING_NOISE = re.compile(
    r"[,\s]+(?:please|thanks|thank you|for me|okay|ok|alright)\s*[.!?]*$", re.I
)


# ---------------------------------------------------------------------------
# Phonetic / homophone corrections
# ---------------------------------------------------------------------------

DIRECTIONS = r"(?:up|down|left|right|top|bottom)"


def _rule(pattern: str, repl: str, name: str) -> Tuple[re.Pattern, str, str]:
    return (re.compile(pattern, re.I), repl, name)


# Distinctive enough to rewrite anywhere in the utterance.
APP_NAME_RULES = [
    _rule(r"\byou[\s-]*tube\b|\bu[\s-]*tube\b|\butube\b|\byoutub\b|\byuotube\b|\byou\s*chube\b", "youtube", "youtube"),
    _rule(r"\bwhats\s*app\b|\bwhat'?s\s*app\b|\bwatts\s*app\b|\bwhat\s*sapp\b", "whatsapp", "whatsapp"),
    _rule(r"\b(open|launch|start|use|message|text|on|in|via)\s+what'?s\s*up\b", r"\1 whatsapp", "whatsapp-ctx"),
    _rule(r"\bg[\s-]*mail\b|\bjee\s*mail\b|\bgee\s*mail\b", "gmail", "gmail"),
    _rule(r"\bkrome\b|\bcrome\b|\bchrom\b|\bchroom\b|\bcrom\b", "chrome", "chrome"),
    _rule(r"\blinked\s*in\b|\blinkdin\b|\blinkden\b|\blink\s*din\b|\blinkin\b", "linkedin", "linkedin"),
    _rule(r"\binsta\s*gram\b|\binstragram\b|\binstergram\b|\binstgram\b", "instagram", "instagram"),
    _rule(r"\bsportify\b|\bspotifi\b|\bspotfy\b|\bspoty\s*fy\b", "spotify", "spotify"),
    _rule(r"\bchat\s*(?:gpt|g\s*p\s*t|gbt|jpt|jipiti)\b|\bchad\s*gpt\b", "chatgpt", "chatgpt"),
    _rule(r"\bperplex\s*city\b|\bperplexit(?:y|ee)\b", "perplexity", "perplexity"),
    _rule(r"\bplay\s*store\b|\bplaystore\b", "play store", "playstore"),
    _rule(r"\bone\s*drive\b", "onedrive", "onedrive"),
    _rule(r"\bpintrest\b|\bpinrest\b|\bpin\s*interest\b", "pinterest", "pinterest"),
    _rule(r"\bcorsera\b|\bcursera\b|\bcoursara\b|\bcoursea\b", "coursera", "coursera"),
    _rule(r"\bjemini\b|\bgemeni\b|\bgemini's\b", "gemini", "gemini"),
    _rule(r"\bsamsang\b|\bsamsong\b|\bsam\s*sung\b", "samsung", "samsung"),
    _rule(r"\bgalery\b|\bgallary\b", "gallery", "gallery"),
    _rule(r"\bcalcultor\b|\bcalculater\b|\bcalculater\b", "calculator", "calculator"),
    _rule(r"\bcamra\b|\bkamera\b|\bcamara\b", "camera", "camera"),
]

# Device and control vocabulary.
CONTROL_RULES = [
    _rule(r"\bwi[\s-]*fi\b|\bwhy[\s-]*fi\b|\bwifey\b|\bwyfy\b", "wifi", "wifi"),
    _rule(r"\bblue[\s-]*tooth\b|\bblu[\s-]*tooth\b|\bbluthooth\b|\bblutooth\b", "bluetooth", "bluetooth"),
    _rule(r"\bflash[\s-]*light\b", "flashlight", "flashlight"),
    _rule(r"\btorche\b", "torch", "torch"),
    _rule(r"\bhot[\s-]*spot\b", "hotspot", "hotspot"),
    _rule(r"\bair[\s-]*plane\b|\baeroplane\b|\bairplain\b|\baerplane\b", "airplane", "airplane"),
    _rule(r"\bdon'?t\s+disturb\b", "do not disturb", "dnd"),
    _rule(r"\bscreen[\s-]*shot\b", "screenshot", "screenshot"),
    _rule(r"\bvolum\b|\bvollum\b|\bvolumn\b|\bwolume\b|\bvoloome\b", "volume", "volume"),
    _rule(r"\bbrightnes\b|\bbrightniss\b|\bbright[\s-]ness\b|\bbrighness\b", "brightness", "brightness"),
    _rule(r"\bvibrasion\b|\bvibraton\b", "vibration", "vibration"),
    _rule(r"\bnotifcation\b|\bnotifiction\b", "notification", "notification"),
    _rule(r"\bbatery\b|\bbattry\b", "battery", "battery"),
    # Whisper routinely drops the second f, flipping the meaning of the command.
    _rule(r"\bturn\s+of\b(?!f)", "turn off", "turn-off"),
    _rule(r"\bturnoff\b", "turn off", "turnoff"),
    _rule(r"\bturnon\b", "turn on", "turnon"),
    _rule(r"\btern\b(?=\s+(?:on|off|up|down))", "turn", "turn"),
    _rule(r"\bincrese\b|\bincreese\b", "increase", "increase"),
    _rule(r"\bdecrese\b|\bdecreese\b", "decrease", "decrease"),
    _rule(r"\bmaxium\b|\bmaximam\b|\bmaximun\b", "maximum", "maximum"),
    _rule(r"\bminimun\b|\bminimam\b", "minimum", "minimum"),
    _rule(r"\bper\s*cent\b|\bpercen\b", "percent", "percent"),
]

# Action verbs — several need context so ordinary English survives intact.
ACTION_RULES = [
    # "school down" / "stroll up": only next to a direction.
    _rule(rf"\b(?:school|scrol|scrawl|skroll|screwl|stroll|scroal)\b(?=\s+(?:{DIRECTIONS}|to\b|the\b))",
          "scroll", "scroll-ctx"),
    _rule(r"^(?:school|scrol|scrawl|skroll|stroll|scroal)\b", "scroll", "scroll-start"),
    _rule(rf"\b(?:wipe|swype|sweip|swaip)\b(?=\s+(?:{DIRECTIONS}))", "swipe", "swipe"),
    # "describe" is a real command ("describe the screen"), so only the tap
    # form becomes "subscribe".
    _rule(r"\b(click|tap|press|hit)\s+(?:describe|subscribed|sub\s*scribe|subscript)\b",
          r"\1 subscribe", "subscribe"),
    _rule(r"\b(?:tab|tap on|tab on)\b(?=\s+(?:the|that|this|on)\b)", "tap", "tap"),
    _rule(r"^tape\s+(?=\w)", "type ", "type-start"),
    _rule(r"\bserch\b|\bsurch\b|\bsearh\b", "search", "search"),
    _rule(r"\bopan\b|\boppen\b|\bopn\b", "open", "open"),
    _rule(r"\bcloze\b|\bclos\b(?!e)", "close", "close"),
    _rule(r"\binstal\b|\bin\s+stall\b", "install", "install"),
    _rule(r"\bun\s+install\b", "uninstall", "uninstall"),
    _rule(r"\bpaws\b|\bpauze\b", "pause", "pause"),
    _rule(r"\bprevius\b|\bprevios\b|\bprevius\b", "previous", "previous"),
    _rule(r"\bnekst\b", "next", "next"),
    _rule(r"\bgo\s+bak\b|\bgo\s+bac\b", "go back", "go-back"),
    _rule(r"\brecents\b", "recent apps", "recents"),
]

PHONETIC_RULES = APP_NAME_RULES + CONTROL_RULES + ACTION_RULES


# ---------------------------------------------------------------------------
# Spoken numbers
# ---------------------------------------------------------------------------

NUMBER_WORDS: Dict[str, int] = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100,
}
TENS = {"twenty", "thirty", "forty", "fourty", "fifty", "sixty", "seventy", "eighty", "ninety"}

# Numbers are only spelled out as digits where a number is meaningful; leaving
# them as words elsewhere keeps search queries ("three body problem") intact.
NUMERIC_CONTEXT = re.compile(
    r"\b(?:volume|brightness|percent|level|set|timeout|seconds?|minutes?|"
    r"scroll|swipe|times|to)\b", re.I
)


def _convert_numbers(text: str) -> Tuple[str, bool]:
    if not NUMERIC_CONTEXT.search(text):
        return text, False

    tokens = text.split()
    out: List[str] = []
    i = 0
    changed = False
    while i < len(tokens):
        word = tokens[i].lower().strip(".,!?")
        if word in NUMBER_WORDS:
            value = NUMBER_WORDS[word]
            consumed = 1
            # "twenty five" → 25
            if word in TENS and i + 1 < len(tokens):
                nxt = tokens[i + 1].lower().strip(".,!?")
                if nxt in NUMBER_WORDS and NUMBER_WORDS[nxt] < 10:
                    value += NUMBER_WORDS[nxt]
                    consumed = 2
            # "one hundred" → 100
            elif value < 10 and i + 1 < len(tokens):
                if tokens[i + 1].lower().strip(".,!?") == "hundred":
                    value *= 100
                    consumed = 2
            out.append(str(value))
            i += consumed
            changed = True
        else:
            out.append(tokens[i])
            i += 1
    return " ".join(out), changed


# ---------------------------------------------------------------------------
# App-name correction against the device's real app list
# ---------------------------------------------------------------------------

APP_VERB_SLOT = re.compile(
    r"\b(?P<verb>open|launch|start|run|go to|switch to|close|quit|kill|"
    r"install|download|uninstall|remove)\s+(?:the\s+)?(?P<app>[a-z][a-z0-9'&.\- ]{1,28}?)\s*$",
    re.I,
)
APP_TAIL_SLOT = re.compile(
    r"\b(?:on|in|inside|using|with|via|from)\s+(?:the\s+)?(?P<app>[a-z][a-z0-9'&.\- ]{1,28}?)\s*$",
    re.I,
)

# Generic words that follow app verbs but never name an app.
STOP_SLOTS = {
    "it", "this", "that", "them", "screen", "the screen", "top", "bottom",
    "page", "video", "song", "music", "tab", "app", "apps", "everything",
    "all", "here", "there", "device", "menu", "list", "keyboard", "notification",
    "notifications", "window", "windows", "file", "link", "image", "picture",
    "photo", "one", "search", "google search", "internet", "web", "browser",
}


def _similarity(a: str, b: str) -> float:
    """Fuzzy score that also rewards a match once spaces are ignored."""
    base = SequenceMatcher(None, a, b).ratio()
    squashed = SequenceMatcher(None, a.replace(" ", ""), b.replace(" ", "")).ratio()
    return max(base, squashed)


class SpeechNormalizer:
    """Turns a raw transcript into a command string, or rejects it."""

    def __init__(
        self,
        app_vocabulary: Optional[Callable[[], Sequence[str]]] = None,
        fuzzy_threshold: float = 0.72,
    ) -> None:
        self._app_vocabulary = app_vocabulary
        self.fuzzy_threshold = fuzzy_threshold

    # -- public ---------------------------------------------------------
    def normalize(self, raw: str) -> NormalizedSpeech:
        corrections: List[str] = []
        text = (raw or "").strip()

        if not text:
            return NormalizedSpeech(raw, "", accepted=False, reason="empty transcript")

        cleaned = self._basic_clean(text)
        if self._is_hallucination(cleaned):
            return NormalizedSpeech(raw, "", accepted=False, reason="silence artifact")

        stripped = self._strip_noise_words(cleaned)
        if stripped != cleaned:
            corrections.append("fillers")
        text = stripped

        text, applied = self._apply_phonetics(text)
        corrections.extend(applied)

        text, numbers_changed = _convert_numbers(text)
        if numbers_changed:
            corrections.append("numbers")

        text, deduped = self._collapse_stutter(text)
        if deduped:
            corrections.append("stutter")

        text, app_fix = self._correct_app_name(text)
        if app_fix:
            corrections.append(app_fix)

        text = re.sub(r"\s+", " ", text).strip(" ,.")

        rejection = self._reject_reason(text)
        if rejection:
            return NormalizedSpeech(raw, "", corrections, accepted=False, reason=rejection)

        return NormalizedSpeech(raw, text, corrections, accepted=True)

    # -- stages ---------------------------------------------------------
    @staticmethod
    def _basic_clean(text: str) -> str:
        text = text.replace("\u2019", "'").replace("\u2018", "'")
        text = re.sub(r"\s+", " ", text).strip()
        # Whisper punctuates full sentences; the intent engine wants a phrase.
        return text.strip(" \t\r\n.!?,;:")

    @staticmethod
    def _is_hallucination(text: str) -> bool:
        probe = text.strip().lower()
        return any(p.fullmatch(probe) for p in HALLUCINATIONS)

    @staticmethod
    def _strip_noise_words(text: str) -> str:
        for pattern in FILLERS:
            text = pattern.sub(" ", text)
        text = re.sub(r"\s+", " ", text).strip()
        text = WAKE_WORDS.sub("", text)
        text = LEADING_NOISE.sub("", text)
        text = TRAILING_NOISE.sub("", text)
        # A bare "please" mid-sentence adds nothing for the classifier.
        text = re.sub(r"\bplease\b", " ", text, flags=re.I)
        return re.sub(r"\s+", " ", text).strip(" ,.")

    @staticmethod
    def _apply_phonetics(text: str) -> Tuple[str, List[str]]:
        applied: List[str] = []
        for pattern, repl, name in PHONETIC_RULES:
            new_text, count = pattern.subn(repl, text)
            if count:
                applied.append(name)
                text = new_text
        return text, applied

    @staticmethod
    def _collapse_stutter(text: str) -> Tuple[str, bool]:
        tokens = text.split()
        out: List[str] = []
        changed = False
        for token in tokens:
            if out and token.lower() == out[-1].lower() and token.lower() not in {"very", "no"}:
                changed = True
                continue
            out.append(token)
        return " ".join(out), changed

    def _known_apps(self) -> List[str]:
        if not self._app_vocabulary:
            return []
        try:
            return [a for a in self._app_vocabulary() if a]
        except Exception:
            return []

    def _correct_app_name(self, text: str) -> Tuple[str, str]:
        apps = self._known_apps()
        if not apps:
            return text, ""

        for pattern, threshold in ((APP_VERB_SLOT, self.fuzzy_threshold),
                                   (APP_TAIL_SLOT, self.fuzzy_threshold + 0.06)):
            match = pattern.search(text)
            if not match:
                continue
            slot = match.group("app").strip()
            slot_l = slot.lower()
            if not slot_l or slot_l in STOP_SLOTS or "." in slot_l:
                continue
            # Already an installed app — nothing to guess at.
            if any(slot_l == a.lower() for a in apps):
                continue

            start, end = match.span("app")

            # "open lufthansa airlines", "install temu app": the app name is
            # there, wrapped in words that drag the fuzzy score below any
            # useful threshold. Longest wins so "google play store" doesn't
            # collapse to "Google".
            contained = [
                a for a in apps
                if re.search(rf"\b{re.escape(a.lower())}\b", slot_l)
            ]
            if contained:
                best = max(contained, key=len)
                return text[:start] + best + text[end:], f"app:{slot}->{best}"

            best, best_score = "", 0.0
            for app in apps:
                score = _similarity(slot_l, app.lower())
                if score > best_score:
                    best, best_score = app, score

            if best and best_score >= threshold and best.lower() != slot_l:
                return text[:start] + best + text[end:], f"app:{slot}->{best}"
            break

        return text, ""

    @staticmethod
    def _reject_reason(text: str) -> str:
        if not text or len(text) < 2:
            return "too short"
        tokens = [t for t in re.split(r"\W+", text.lower()) if t]
        if not tokens:
            return "no words"
        if len(tokens) == 1:
            token = tokens[0]
            if token in SHORT_COMMANDS:
                return ""
            if token in NOISE_TOKENS or len(token) < 3:
                return f"ignored filler '{token}'"
        return ""
