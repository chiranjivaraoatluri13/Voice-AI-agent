# =========================
# FILE: agent/screen_controller.py
# =========================
"""
Screen controller — v4 SPEED.

Key change: Vision model's background thread pre-captures screenshots.
When vision fallback is needed, screenshot is already ready.

Flow for "click subscribe":
  1. Check UI_ELEMENT_KNOWLEDGE → found? tap (0ms)
  2. UI tree search → found? tap (~1s)
  3. OCR search → found? tap (~1.5s)  
  4. Vision model with PRE-CACHED screenshot → tap (~3-5s, was 8-12s)
"""

import time
import os
import tempfile
from typing import Optional, List
from agent.adb import AdbClient
from agent.device import DeviceController
from agent.ui_analyzer import UIAnalyzer, UIElement
from agent.ocr_engine import OCREngine
from agent.ollama_vision import OllamaVision, VisionResult
from agent.query_router import QueryRouter, QueryIntent


UI_ELEMENT_KNOWLEDGE = {
    "send": ["Send", "send message", "Send message"],
    "search": ["Search", "search", "Search button"],
    "back": ["Back", "Navigate up", "Go back"],
    "close": ["Close", "Dismiss", "Cancel"],
    "more": ["More options", "More", "Overflow"],
    "menu": ["More options", "Menu", "Navigation"],
    "settings": ["Settings", "Preferences"],
    "play": ["Play", "Play video"],
    "pause": ["Pause", "Pause video"],
    "like": ["Like", "Like button", "Heart"],
    "share": ["Share", "Share button"],
    "subscribe": ["Subscribe", "Subscribe button"],
    "download": ["Download", "Save"],
    "shutter": ["Shutter", "Capture", "Take photo"],
    "switch camera": ["Switch camera", "Flip"],
    "flash": ["Flash", "Flash toggle"],
    "add": ["Add", "Create", "New", "Compose"],
    "delete": ["Delete", "Remove", "Trash"],
    "edit": ["Edit", "Modify"],
    "save": ["Save", "Done"],
    "cancel": ["Cancel", "Dismiss"],
    "refresh": ["Refresh", "Reload"],
    "comment": ["Comment", "Comments"],
    "follow": ["Follow"],
    "profile": ["Profile", "Account", "Avatar"],
    "home": ["Home", "Home tab"],
    "notifications": ["Notifications", "Alerts"],
    "copy": ["Copy", "Copy link", "Copy text"],
    "paste": ["Paste"],
    "forward": ["Forward"],
    "reply": ["Reply"],
    "attach": ["Attach", "Attachment", "Attach file"],
}

VISION_ONLY_WORDS = {
    "red", "blue", "green", "yellow", "orange", "purple", "pink",
    "color", "colored", "car", "cat", "dog", "person", "face",
    "photo of", "image of", "picture of", "thumbnail",
}


class ScreenController:
    def __init__(self, adb: AdbClient, device: DeviceController) -> None:
        self.adb = adb
        self.device = device
        self.ui_analyzer = UIAnalyzer(adb)
        self.ocr = OCREngine()
        self.vision = OllamaVision(model="llava-phi3")
        self.router = QueryRouter()
        
        # Legacy screenshot path (for OCR which needs a file)
        self.screenshot_path = os.path.join(tempfile.gettempdir(), "screenshot.png")
        self.last_screenshot_time = 0
        self.screenshot_cache_duration = 3

        try:
            w, h = device.screen_size()
            self.vision.set_screen_size(w, h)
        except Exception:
            pass
    
    def start_watching(self) -> None:
        """Start background vision watching. Call after init."""
        self.vision.start_watching(self.adb)
    
    def stop_watching(self) -> None:
        self.vision.stop_watching()

    def capture_screenshot(self, force: bool = False) -> str:
        """Capture screenshot to file (for OCR). Uses vision cache when possible."""
        now = time.time()
        if not force and (now - self.last_screenshot_time) < self.screenshot_cache_duration:
            if os.path.exists(self.screenshot_path):
                return self.screenshot_path
        try:
            self.adb.run(["shell", "screencap", "-p", "/sdcard/screenshot.png"])
            self.adb.run(["pull", "/sdcard/screenshot.png", self.screenshot_path])
            self.last_screenshot_time = now
            return self.screenshot_path
        except Exception as e:
            print(f"⚠️ Screenshot failed: {e}")
            return ""

    # =========================================================
    # MAIN ENTRY
    # =========================================================
    
    # Words to strip from search queries (action verbs, filler, UI type words)
    STRIP_WORDS = {
        "click", "tap", "select", "press", "on", "the", "a", "an",
        "that", "this", "with", "video", "post", "button", "icon",
        "link", "image", "photo", "picture", "thumbnail", "item",
        "reel", "story", "pin", "result", "it",
    }
    
    def _clean_search_query(self, query: str) -> str:
        """
        Strip action verbs and UI-type words to get the actual content to search for.
        "click on how a hungry video" → "how hungry"
        "tap the subscribe button" → "subscribe"  
        "select the cooking post" → "cooking"
        """
        words = query.lower().split()
        # Remove strip words but keep at least 1 word
        cleaned = [w for w in words if w not in self.STRIP_WORDS]
        if not cleaned:
            # All words were stripped, return original minus just verbs
            verbs = {"click", "tap", "select", "press", "open", "find", "choose"}
            cleaned = [w for w in words if w not in verbs]
        return " ".join(cleaned) if cleaned else query
    
    def execute_query(self, query: str) -> bool:
        target = query.strip()
        target_lower = target.lower()
        
        # Check for ordinal/position queries: "the first post", "second video"
        ordinal_result = self._check_ordinal(target_lower)
        if ordinal_result:
            pos, item_type = ordinal_result
            return self._find_nth_item_and_tap(pos, item_type)
        
        # Check if this REQUIRES vision (colors, images)
        needs_vision = any(w in target_lower for w in VISION_ONLY_WORDS)
        if needs_vision:
            return self._vision_find_and_tap_fast(target)
        
        # Clean the query for text search
        search_text = self._clean_search_query(target_lower)
        print(f"🔍 Searching: '{search_text}'")
        
        # FAST PATH: UI tree
        if self._try_content_desc(search_text):
            return True
        if self._try_ui_tree_search(search_text):
            return True
        
        # OCR fallback
        if self.ocr.available:
            if self._try_ocr_search(search_text):
                return True
        
        # Vision LAST
        if self.vision.available:
            print(f"👁️ Vision fallback...")
            return self._vision_find_and_tap_fast(target)
        
        print(f"❌ Not found: {target}")
        return False
    
    def _check_ordinal(self, query: str):
        """Check if query contains ordinal like 'first post', 'second video'."""
        import re
        ordinals = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
                    "1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5, "last": -1}
        m = re.match(r'(?:the\s+)?(\w+)\s+(.+)', query)
        if m and m.group(1) in ordinals:
            return (ordinals[m.group(1)], m.group(2).strip())
        return None
    
    def _find_nth_item_and_tap(self, position: int, item_type: str) -> bool:
        """Find the Nth item of a type and tap it."""
        print(f"🎯 Finding #{position} {item_type}...")
        
        # Try UI tree first
        items = self._find_items_ui(item_type)
        if items:
            idx = position - 1 if position > 0 else position
            if 0 <= idx < len(items):
                self.device.tap(*items[idx].center)
                label = items[idx].text or items[idx].content_desc or items[idx].class_name
                print(f"✅ #{position} {item_type}: {label}")
                return True
            elif idx < 0 and len(items) >= abs(idx):
                self.device.tap(*items[idx].center)
                print(f"✅ Last {item_type}")
                return True
        
        # Vision fallback
        if self.vision.available:
            print(f"👁️ Using vision for #{position} {item_type}...")
            ords = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth"}
            ordinal_word = ords.get(position, f"{position}th")
            result = self.vision.find_element_fast(f"the {ordinal_word} {item_type}")
            if result.coordinates and result.confidence > 0.4:
                self.device.tap(*result.coordinates)
                print(f"✅ #{position} {item_type} (vision)")
                return True
        
        print(f"❌ Could not find #{position} {item_type}")
        return False

    # =========================================================
    # Strategy 1: Content-desc knowledge
    # =========================================================
    def _try_content_desc(self, target_lower: str) -> bool:
        known = UI_ELEMENT_KNOWLEDGE.get(target_lower)
        if not known:
            for key, descs in UI_ELEMENT_KNOWLEDGE.items():
                if key in target_lower or target_lower in key:
                    known = descs
                    break
        if not known:
            return False
        
        self.ui_analyzer.capture_ui_tree()
        for elem in self.ui_analyzer.last_elements:
            desc = elem.content_desc.lower()
            for k in known:
                if k.lower() in desc or desc in k.lower():
                    self.device.tap(*elem.center)
                    print(f"✅ {elem.content_desc}")
                    return True
        return False

    # =========================================================
    # Strategy 2: UI tree search
    # =========================================================
    def _try_ui_tree_search(self, target: str) -> bool:
        """
        Search UI tree with smart matching:
        1. Exact substring match (highest confidence)
        2. Word-overlap match (handles partial queries)
        """
        self.ui_analyzer.capture_ui_tree()
        if not self.ui_analyzer.last_elements:
            return False
        
        tl = target.lower().strip()
        if not tl:
            return False
        query_words = set(tl.split())
        
        # Pass 1: Exact substring match in text
        for elem in self.ui_analyzer.last_elements:
            if elem.text and tl in elem.text.lower():
                self.device.tap(*elem.center)
                print(f"✅ {elem.text}")
                return True
        
        # Pass 2: Exact substring in content-desc
        for elem in self.ui_analyzer.last_elements:
            if elem.content_desc and tl in elem.content_desc.lower():
                self.device.tap(*elem.center)
                print(f"✅ {elem.content_desc}")
                return True
        
        # Pass 3: Word-overlap scoring (for partial matches)
        # "how hungry" should match "How a Hungry Wolf Changed Rivers"
        best_elem = None
        best_score = 0
        
        for elem in self.ui_analyzer.last_elements:
            text = (elem.text or "").lower()
            desc = (elem.content_desc or "").lower()
            combined = text + " " + desc
            if not combined.strip():
                continue
            
            combined_words = set(combined.split())
            
            # Count how many query words appear in element
            overlap = query_words & combined_words
            if len(overlap) < 1:
                continue
            
            # Score: fraction of query words matched * length bonus
            score = len(overlap) / len(query_words)
            # Bonus for having more text (likely content, not toolbar)
            if len(text) > 20:
                score += 0.1
            # Bonus for clickable
            if elem.clickable:
                score += 0.05
            
            if score > best_score:
                best_score = score
                best_elem = elem
        
        # Only tap if we matched at least 50% of query words
        if best_elem and best_score >= 0.5:
            self.device.tap(*best_elem.center)
            label = best_elem.text or best_elem.content_desc
            print(f"✅ {label} ({best_score:.0%} match)")
            return True
        
        return False

    # =========================================================
    # Strategy 3: OCR
    # =========================================================
    def _try_ocr_search(self, target: str) -> bool:
        screenshot = self.capture_screenshot()
        if not screenshot:
            return False
        matches = self.ocr.find_text(screenshot, target)
        if matches:
            self.device.tap(*matches[0].center)
            print(f"✅ {matches[0].text} (OCR)")
            return True
        fuzzy = self.ocr.find_text_fuzzy(screenshot, target, threshold=0.7)
        if fuzzy:
            _, match = fuzzy[0]
            self.device.tap(*match.center)
            print(f"✅ {match.text} (OCR fuzzy)")
            return True
        return False

    # =========================================================
    # Strategy 4: Vision — FAST (uses background screenshot cache)
    # =========================================================
    def _vision_find_and_tap_fast(self, target: str) -> bool:
        """Use vision model. Captures screenshot on demand (cached 2s)."""
        result = self.vision.find_element_fast(target)
        if result.coordinates and result.confidence > 0.4:
            self.device.tap(*result.coordinates)
            print(f"✅ {result.description} (vision)")
            return True
        print(f"❌ Vision couldn't find: {target}")
        return False
    
    def _vision_find_and_tap(self, target: str) -> bool:
        """Legacy: capture + find. Use _fast version when possible."""
        return self._vision_find_and_tap_fast(target)

    # =========================================================
    # INFO
    # =========================================================
    def _execute_info(self, intent: QueryIntent) -> bool:
        self.ui_analyzer.capture_ui_tree(force_refresh=True)
        ui_desc = self.ui_analyzer.describe_screen()
        print(f"\n📱 {ui_desc}")
        
        if intent.require_vision and self.vision.available:
            desc = self.vision.describe_screen_fast()
            print(f"\n🖼️ {desc}")
        print()
        return True

    # =========================================================
    # POSITION
    # =========================================================
    def _execute_position(self, intent: QueryIntent) -> bool:
        items = self._find_items_ui(intent.target)
        if items and intent.position:
            idx = intent.position - 1 if intent.position > 0 else intent.position
            if 0 <= idx < len(items) or idx < 0:
                self.device.tap(*items[idx].center)
                print(f"✅ #{intent.position} {intent.target}")
                return True
        if self.vision.available:
            result = self.vision.find_element_fast(
                f"the {intent.position}{'st' if intent.position==1 else 'nd' if intent.position==2 else 'rd' if intent.position==3 else 'th'} {intent.target}")
            if result.coordinates and result.confidence > 0.5:
                self.device.tap(*result.coordinates)
                return True
        return False

    # =========================================================
    # SCROLL-FIND
    # =========================================================
    def _execute_scroll_find(self, intent: QueryIntent) -> bool:
        for i in range(10):
            self.ui_analyzer.capture_ui_tree(force_refresh=True)
            elements = self.ui_analyzer.search(intent.target)
            if elements:
                self.device.tap(*elements[0].center)
                print(f"✅ Found: {intent.target}")
                return True
            print(f"   Scroll {i+1}/10...")
            self.device.scroll_once("DOWN")
            time.sleep(0.4)
        return False

    # =========================================================
    # Helpers
    # =========================================================
    def _find_items_ui(self, item_type: str) -> list:
        """Find repeating items (videos, posts, etc.) on screen."""
        self.ui_analyzer.capture_ui_tree(force_refresh=True)
        
        # Use the multi-strategy detect_list_items
        items = self.ui_analyzer.detect_list_items()
        
        if items:
            print(f"   Found {len(items)} items via UI tree")
            # Debug: show first few
            for i, item in enumerate(items[:3]):
                label = item.text or item.content_desc or item.class_name
                print(f"   #{i+1}: {label[:50]} [{item.bounds}]")
            return items
        
        print(f"   ⚠️ No items detected in UI tree")
        return []

    def ask(self, question: str) -> str:
        if self.vision.available:
            b64 = self.vision.capture_screenshot_b64()
            if b64:
                r = self.vision.analyze_image(b64, f"Question: {question}\nAnswer concisely.",
                                               0.2, is_b64=True)
                return r.description
        self.ui_analyzer.capture_ui_tree(force_refresh=True)
        return self.ui_analyzer.describe_screen()

    def find_and_tap(self, description: str) -> bool:
        return self.execute_query(description)

    def list_visible_text(self) -> list:
        self.ui_analyzer.capture_ui_tree()
        return [e.text for e in self.ui_analyzer.last_elements if e.text and len(e.text) > 1]
