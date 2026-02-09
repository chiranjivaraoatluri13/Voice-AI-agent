# =========================
# FILE: agent/intent_engine.py
# =========================
"""
Intent Understanding Engine
Converts free-form natural language to structured actions
"""

import re
import json
from typing import Optional, Dict, List, Any
from dataclasses import dataclass
from agent.schema import Command

# Try to import Ollama for advanced NLP
try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False


@dataclass
class Intent:
    """Parsed user intent"""
    primary_action: str  # What to do: "open_app", "send_message", "find_visual", etc.
    target: Optional[str] = None  # Target: "youtube", "mom", "subscribe button"
    app: Optional[str] = None  # Specific app needed
    text: Optional[str] = None  # Text to type
    description: Optional[str] = None  # Visual description
    modifiers: Dict[str, Any] = None  # Additional parameters
    confidence: float = 0.0
    
    def __post_init__(self):
        if self.modifiers is None:
            self.modifiers = {}


class IntentEngine:
    """
    Core natural language understanding engine.
    Converts free-form speech to structured intents.
    """
    
    def __init__(self, use_llm: bool = True):
        self.use_llm = use_llm and OLLAMA_AVAILABLE
        self.model = "llama3.2:latest"
        
        if self.use_llm:
            self._check_llm()
    
    def _check_llm(self):
        """Check if LLM is available"""
        try:
            models = ollama.list()
            if not any(self.model in m['name'] for m in models.get('models', [])):
                print(f"⚠️ LLM model not found. Run: ollama pull {self.model}")
                self.use_llm = False
        except Exception:
            print("⚠️ Ollama not running. Falling back to patterns.")
            self.use_llm = False
    
    # ===========================
    # MAIN UNDERSTANDING FLOW
    # ===========================
    
    def understand(self, user_input: str) -> Intent:
        """
        Main entry point: Convert natural language to intent.
        
        Flow:
        1. Try pattern-based understanding (fast)
        2. If ambiguous, use LLM (smart)
        3. Return structured intent
        """
        user_input = user_input.strip()
        
        if not user_input:
            return Intent(primary_action="unknown", confidence=0.0)
        
        # Try quick pattern matching first
        intent = self._pattern_understand(user_input)
        
        # If low confidence and LLM available, use it
        if intent.confidence < 0.7 and self.use_llm:
            llm_intent = self._llm_understand(user_input)
            if llm_intent and llm_intent.confidence > intent.confidence:
                intent = llm_intent
        
        return intent
    
    # ===========================
    # PATTERN-BASED UNDERSTANDING
    # ===========================
    
    def _pattern_understand(self, text: str) -> Intent:
        """Fast pattern-based understanding"""
        t = text.lower().strip()
        
        # ===== MESSAGING PATTERNS =====
        # "send hi to mom in whatsapp"
        # "message john saying I'm coming"
        # "whatsapp sarah that I'm late"
        
        msg_patterns = [
            (r'(?:send|text|message|whatsapp)\s+(?:to\s+)?(\w+)\s+(?:saying|that|:)?\s*(.+)', 'send_message'),
            (r'(?:send|text)\s+(.+?)\s+to\s+(\w+)', 'send_message'),
            (r'whatsapp\s+(\w+)\s+(.+)', 'send_message'),
            (r'tell\s+(\w+)\s+(?:that\s+)?(.+)', 'send_message'),
        ]
        
        for pattern, action in msg_patterns:
            match = re.search(pattern, t)
            if match:
                # Extract recipient and message
                groups = match.groups()
                if len(groups) >= 2:
                    # Pattern varies, need to determine which is recipient
                    if action == 'send_message':
                        # Check if "to" is in pattern
                        if 'to' in pattern:
                            message, recipient = groups
                        else:
                            recipient, message = groups
                        
                        return Intent(
                            primary_action="send_message",
                            target=recipient.strip(),
                            text=message.strip(),
                            app="whatsapp",
                            confidence=0.9
                        )
        
        # ===== APP-SPECIFIC VISUAL SEARCH =====
        # "open the pin with red car"
        # "tap on the video about cats"
        # "click the post by john"
        
        visual_app_patterns = [
            (r'(?:open|click|tap|select)\s+(?:the\s+)?(\w+)\s+(?:with|about|by|showing)\s+(.+)', 'app_visual_search'),
            (r'(?:find|show)\s+(?:the\s+)?(\w+)\s+(?:with|about|of)\s+(.+)', 'app_visual_search'),
        ]
        
        for pattern, action in visual_app_patterns:
            match = re.search(pattern, t)
            if match:
                item_type, description = match.groups()
                
                # Determine app from item type
                app_map = {
                    'pin': 'pinterest',
                    'video': 'youtube',
                    'post': 'instagram',
                    'tweet': 'twitter',
                    'song': 'spotify',
                    'photo': 'photos',
                }
                
                app = app_map.get(item_type, None)
                
                return Intent(
                    primary_action="find_and_open",
                    target=item_type,
                    description=description.strip(),
                    app=app,
                    modifiers={'search_query': description.strip()},
                    confidence=0.85
                )
        
        # ===== SEARCH PATTERNS =====
        # "search for cat videos on youtube"
        # "find recipes in pinterest"
        # "look for workout music"
        
        search_patterns = [
            (r'(?:search|find|look)\s+(?:for\s+)?(.+?)\s+(?:on|in)\s+(\w+)', 'search_in_app'),
            (r'(?:show me|find me)\s+(.+)', 'search'),
        ]
        
        for pattern, action in search_patterns:
            match = re.search(pattern, t)
            if match:
                groups = match.groups()
                if len(groups) == 2:
                    query, app = groups
                    return Intent(
                        primary_action="search",
                        target=query.strip(),
                        app=app.strip(),
                        confidence=0.9
                    )
                elif len(groups) == 1:
                    query = groups[0]
                    return Intent(
                        primary_action="search",
                        target=query.strip(),
                        confidence=0.75
                    )
        
        # ===== VISUAL INTERACTION =====
        # "tap on the red button"
        # "click the subscribe button"
        # "select the first video"
        # "tap the profile icon"
        
        visual_interaction_patterns = [
            (r'(?:tap|click|select|press|hit)\s+(?:on\s+)?(?:the\s+)?(.+)', 'visual_tap'),
            (r'(?:find|locate)\s+(?:and\s+)?(?:tap|click)\s+(?:the\s+)?(.+)', 'visual_tap'),
        ]
        
        for pattern, action in visual_interaction_patterns:
            match = re.search(pattern, t)
            if match:
                target = match.group(1).strip()
                
                # Check if it's a position-based query
                position_match = re.search(r'(first|second|third|last|top|bottom)\s+(.+)', target)
                if position_match:
                    position, item = position_match.groups()
                    return Intent(
                        primary_action="visual_tap",
                        target=item.strip(),
                        modifiers={'position': position},
                        confidence=0.85
                    )
                
                return Intent(
                    primary_action="visual_tap",
                    target=target,
                    confidence=0.8
                )
        
        # ===== SCROLL UNTIL FIND =====
        # "scroll until you find the subscribe button"
        # "scroll down until you see the comments"
        # "keep scrolling until there's a red car"
        
        scroll_find_patterns = [
            (r'scroll\s+(?:down\s+)?(?:until|till)\s+(?:you\s+)?(?:find|see)\s+(.+)', 'scroll_find'),
            (r'(?:keep\s+)?scrolling\s+(?:until|till)\s+(?:there\'s|you see)\s+(.+)', 'scroll_find'),
        ]
        
        for pattern, action in scroll_find_patterns:
            match = re.search(pattern, t)
            if match:
                target = match.group(1).strip()
                return Intent(
                    primary_action="scroll_find",
                    target=target,
                    confidence=0.9
                )
        
        # ===== APP OPENING (must be ABOVE media controls) =====
        # "open youtube", "launch instagram", "open google play store"
        # This MUST come before media checks because "open play store"
        # would otherwise match "play" as media_play.
        
        app_open_patterns = [
            r'(?:open|launch|start|run)\s+(.+)',
            r'(?:go to|switch to)\s+(.+)',
        ]
        
        for pattern in app_open_patterns:
            match = re.search(pattern, t)
            if match:
                app = match.group(1).strip()
                return Intent(
                    primary_action="open_app",
                    app=app,
                    confidence=0.9
                )
        
        # ===== MEDIA CONTROLS =====
        # Only match when NOT preceded by "open", "launch", etc.
        if any(kw in t for kw in ["pause", "stop", "halt"]):
            return Intent(primary_action="media_pause", confidence=0.95)
        
        # "play" only as standalone command or "play music/video", NOT "play store"
        if re.search(r'\b(?:play|resume|continue|unpause)\b', t):
            # Don't trigger for app names containing "play"
            if not any(app_word in t for app_word in ["play store", "playstore", "google play"]):
                return Intent(primary_action="media_play", confidence=0.95)
        
        if any(kw in t for kw in ["next", "skip", "next track", "next song"]):
            return Intent(primary_action="media_next", confidence=0.95)
        
        if any(kw in t for kw in ["previous", "prev", "previous track", "previous song"]):
            return Intent(primary_action="media_previous", confidence=0.95)
        
        # ===== VOLUME =====
        # Covers: "volume up", "volume increase", "sound up", "louder", "turn up",
        #         "increase volume", "raise volume", "sound increase", "sound higher"
        volume_up_kw = [
            "volume up", "volume increase", "increase volume", "raise volume",
            "sound up", "sound increase", "sound higher",
            "louder", "turn up", "crank up",
        ]
        if any(kw in t for kw in volume_up_kw):
            amount = 5 if any(w in t for w in ["lot", "max", "full"]) else 2
            return Intent(primary_action="volume_up", modifiers={'amount': amount}, confidence=0.95)
        
        # Covers: "volume down", "volume decrease", "sound down", "quieter", "turn down",
        #         "decrease volume", "lower volume", "sound decrease", "sound lower"
        volume_down_kw = [
            "volume down", "volume decrease", "decrease volume", "lower volume",
            "sound down", "sound decrease", "sound lower",
            "quieter", "turn down",
        ]
        if any(kw in t for kw in volume_down_kw):
            amount = 5 if any(w in t for w in ["lot", "min"]) else 2
            return Intent(primary_action="volume_down", modifiers={'amount': amount}, confidence=0.95)
        
        # Mute
        if any(kw in t for kw in ["mute", "silence", "shut up"]):
            return Intent(primary_action="volume_down", modifiers={'amount': 10}, confidence=0.95)
        
        # ===== NAVIGATION =====
        if t in ["home", "go home", "home screen"]:
            return Intent(primary_action="go_home", confidence=1.0)
        
        if t in ["back", "go back"]:
            return Intent(primary_action="go_back", confidence=1.0)
        
        # ===== SCROLL =====
        if "scroll down" in t:
            return Intent(primary_action="scroll_down", confidence=0.95)
        
        if "scroll up" in t:
            return Intent(primary_action="scroll_up", confidence=0.95)
        
        # ===== SCREEN INFO =====
        if any(kw in t for kw in ["what", "describe", "show me", "tell me"]):
            return Intent(primary_action="describe_screen", target=text, confidence=0.8)
        
        # Default: unknown
        return Intent(primary_action="unknown", confidence=0.0)
    
    # ===========================
    # LLM-BASED UNDERSTANDING
    # ===========================
    
    def _llm_understand(self, text: str) -> Optional[Intent]:
        """Use LLM for complex natural language understanding"""
        
        prompt = f"""You are an intent parser for an Android device controller.

User input: "{text}"

Analyze the intent and return JSON with this structure:
{{
    "primary_action": "ACTION",
    "target": "what/who to interact with",
    "app": "app name if specified",
    "text": "text to type if applicable",
    "description": "visual description if searching",
    "modifiers": {{}},
    "confidence": 0.0-1.0
}}

Available actions:
- send_message: Send text to someone
- find_and_open: Find and open specific content
- search: Search for something
- visual_tap: Tap on visual element
- scroll_find: Scroll until finding something
- media_play, media_pause, media_next
- volume_up, volume_down
- open_app: Open an application
- go_home, go_back
- scroll_down, scroll_up
- describe_screen: Ask about screen content

Examples:

Input: "send hi to mom in whatsapp"
Output: {{
    "primary_action": "send_message",
    "target": "mom",
    "app": "whatsapp",
    "text": "hi",
    "confidence": 0.95
}}

Input: "tap on the video about cats"
Output: {{
    "primary_action": "visual_tap",
    "target": "video",
    "description": "about cats",
    "confidence": 0.9
}}

Input: "open the pin with red car"
Output: {{
    "primary_action": "find_and_open",
    "target": "pin",
    "app": "pinterest",
    "description": "red car",
    "confidence": 0.95
}}

Input: "scroll until you find subscribe button"
Output: {{
    "primary_action": "scroll_find",
    "target": "subscribe button",
    "confidence": 0.95
}}

Input: "pause video"
Output: {{
    "primary_action": "media_pause",
    "confidence": 0.95
}}

Now analyze: "{text}"
Return ONLY valid JSON:"""

        try:
            response = ollama.chat(
                model=self.model,
                messages=[{'role': 'user', 'content': prompt}],
                options={'temperature': 0.1}
            )
            
            content = response['message']['content'].strip()
            
            # Extract JSON
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                
                return Intent(
                    primary_action=data.get('primary_action', 'unknown'),
                    target=data.get('target'),
                    app=data.get('app'),
                    text=data.get('text'),
                    description=data.get('description'),
                    modifiers=data.get('modifiers', {}),
                    confidence=data.get('confidence', 0.5)
                )
        
        except Exception as e:
            print(f"⚠️ LLM understanding failed: {e}")
        
        return None
    
    # ===========================
    # INTENT TO COMMAND
    # ===========================
    
    def intent_to_command(self, intent: Intent) -> Optional[Command]:
        """Convert Intent to Command for execution"""
        
        action_map = {
            "media_play": "MEDIA_PLAY",
            "media_pause": "MEDIA_PAUSE",
            "media_next": "MEDIA_NEXT",
            "media_previous": "MEDIA_PREVIOUS",
            "volume_up": "VOLUME_UP",
            "volume_down": "VOLUME_DOWN",
            "go_home": "HOME",
            "go_back": "BACK",
            "scroll_down": "SCROLL",
            "scroll_up": "SCROLL",
        }
        
        # Direct action mapping
        if intent.primary_action in action_map:
            cmd_action = action_map[intent.primary_action]
            
            # Special handling for scroll
            if cmd_action == "SCROLL":
                direction = "DOWN" if intent.primary_action == "scroll_down" else "UP"
                return Command(action=cmd_action, direction=direction, amount=1)
            
            # Volume with amount
            if "volume" in intent.primary_action:
                amount = intent.modifiers.get('amount', 1)
                return Command(action=cmd_action, amount=amount)
            
            return Command(action=cmd_action)
        
        # Complex actions
        if intent.primary_action == "open_app":
            return Command(action="OPEN_APP", query=intent.app or intent.target)
        
        if intent.primary_action == "visual_tap":
            return Command(action="VISION_QUERY", query=f"tap {intent.target}")
        
        if intent.primary_action == "scroll_find":
            return Command(action="VISION_QUERY", query=f"scroll until you find {intent.target}")
        
        if intent.primary_action == "describe_screen":
            return Command(action="SCREEN_INFO", query=intent.target)
        
        # send_message, find_and_open, search need multi-step
        # Return complex command
        if intent.primary_action in ["send_message", "find_and_open", "search"]:
            return Command(action="COMPLEX_TASK", query=json.dumps(intent.__dict__))
        
        return None


# =========================
# Global instance
# =========================

_intent_engine = None

def get_intent_engine() -> IntentEngine:
    """Get singleton intent engine"""
    global _intent_engine
    if _intent_engine is None:
        _intent_engine = IntentEngine()
    return _intent_engine
