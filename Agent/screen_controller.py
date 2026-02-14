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
    "subscribe": ["Subscribe", "Subscribe button", "SUBSCRIBE"],
    "unsubscribe": ["Unsubscribe", "Unsubscribe button", "UNSUBSCRIBE"],
    "follow": ["Follow", "FOLLOW"],
    "unfollow": ["Unfollow", "Unfollow button", "UNFOLLOW"],
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
        
        # Start background UI cache watcher
        self.ui_analyzer.start_cache_watcher()
    
    def start_watching(self) -> None:
        """Start background vision watching. Call after init."""
        self.vision.start_watching(self.adb)
    
    def stop_watching(self) -> None:
        self.vision.stop_watching()

    def dump_screen_state(self) -> str:
        """Dump current screen state for debugging."""
        return self.ui_analyzer.dump_screen_elements()

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
        
        # Debug commands
        if target_lower in ["dump", "screen elements", "what's on screen", "what elements"]:
            print("\n" + self.dump_screen_state())
            return True
        
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
        
        # Brute force: search all elements for ANY partial match of target
        print(f"   ⚠️ Standard search failed. Trying brute-force text match...")
        if self._brute_force_text_search(target_lower):
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
        
        self.ui_analyzer.capture_ui_tree(force_refresh=True)
        for elem in self.ui_analyzer.last_elements:
            desc = elem.content_desc.lower()
            for k in known:
                if k.lower() in desc or desc in k.lower():
                    if not elem.clickable and "Button" not in elem.class_name:
                        continue
                    self.device.tap(*elem.center)
                    time.sleep(0.3)
                    print(f"✅ {elem.content_desc}")
                    return True
        return False

    def _brute_force_text_search(self, target: str) -> bool:
        """
        Last-resort search: look for ANY clickable element containing target text.
        Useful when app uses custom element names not in our knowledge base.
        Tries partial matching, case-insensitive, fuzzy matching.
        """
        self.ui_analyzer.capture_ui_tree(force_refresh=True)
        if not self.ui_analyzer.last_elements:
            print(f"   ⚠️ UI tree is empty!")
            return False
        
        target_lower = target.lower()
        # For partial word matching
        target_words = set(target_lower.split())
        candidates = []
        
        # Special keywords with high priority
        high_priority_keywords = {
            "subscribe": 50,
            "unsubscribe": 50,
            "follow": 45,
            "unfollow": 45,
            "like": 40,
            "share": 40,
        }
        
        # Find all clickable elements for debugging
        clickable_elements = [e for e in self.ui_analyzer.last_elements if e.clickable or "Button" in e.class_name]
        if not clickable_elements:
            print(f"   ⚠️ No clickable elements found in UI tree")
            return False
        
        print(f"   📍 Checking {len(clickable_elements)} clickable elements for '{target_lower}'...")
        for i, e in enumerate(clickable_elements[:10], 1):  # Show first 10
            text_preview = (e.text or "")[:40]
            desc_preview = (e.content_desc or "")[:40]
            icon = "🔘"
            if target_lower in (text_preview.lower() + desc_preview.lower()):
                icon = "✓"
            print(f"      {icon} {i}. '{text_preview}' | {desc_preview}")
        
        # Find all elements matching target
        for elem in self.ui_analyzer.last_elements:
            text = (elem.text or "").lower().strip()
            desc = (elem.content_desc or "").lower().strip()
            resource = (elem.resource_id or "").lower()
            
            # Skip empty elements
            if not (text or desc):
                continue
            
            combined = f"{text} {desc} {resource}"
            priority = 0
            match_reason = []
            
            # Special high-priority keywords
            for keyword, boost in high_priority_keywords.items():
                if keyword in combined:
                    priority += boost
                    match_reason.append(f"keyword:{keyword}")
                    break  # Only match first keyword
            
            # Exact match (highest priority)
            if text == target_lower or desc == target_lower:
                priority += 20
                match_reason.append("exact")
            
            # Substring match
            if target_lower in text or target_lower in desc or target_lower in resource:
                priority += 15
                match_reason.append("substring")
            
            # Word overlap (e.g., "subscribe button" matches "subscribe")
            text_words = set(text.split())
            desc_words = set(desc.split())
            combined_words = text_words | desc_words
            word_overlap = len(target_words & combined_words)
            if word_overlap > 0:
                priority += word_overlap * 5
                match_reason.append(f"words:{word_overlap}")
            
            # Starts with target (e.g., "Unsubscribe Now" starts with "unsubscribe")
            if text.startswith(target_lower) or text.startswith(target_lower.split()[0]):
                priority += 8
                match_reason.append("starts_with")
            
            # Bonus for clickable/button
            if elem.clickable:
                priority += 3
            if "Button" in elem.class_name:
                priority += 2
            
            if priority > 0:
                candidates.append((priority, elem, match_reason))
        
        if not candidates:
            print(f"   ℹ️ No matching elements for '{target}'")
            return False
        
        # Sort by priority (highest first)
        candidates.sort(key=lambda x: x[0], reverse=True)
        
        # Tap the best candidate
        best_priority, best_elem, reasons = candidates[0]
        text_label = best_elem.text or best_elem.content_desc
        print(f"   🎯 Best match: '{text_label}' (priority: {best_priority}, match: {'+'.join(reasons)})")
        
        # Double-check coordinates are valid
        try:
            w, h = self.device.screen_size()
            x, y = best_elem.center
            if not (0 < x < w and 0 < y < h):
                print(f"   ⚠️ Coordinates out of bounds: ({x}, {y}) screen: {w}x{h}")
                return False
        except Exception as e:
            print(f"   ⚠️ Could not validate coordinates: {e}")
        
        print(f"   📍 Tapping at ({best_elem.center[0]}, {best_elem.center[1]})")
        self.device.tap(*best_elem.center)
        time.sleep(0.5)  # Extra wait for brute-force matches
        print(f"✅ {text_label}")
        return True

    # =========================================================
    # Strategy 2: UI tree search
    # =========================================================
    def _try_ui_tree_search(self, target: str) -> bool:
        """
        Search UI tree with smart matching:
        1. Exact substring match (highest confidence)
        2. Word-overlap match (handles partial queries)
        """
        self.ui_analyzer.capture_ui_tree(force_refresh=True)
        if not self.ui_analyzer.last_elements:
            print(f"   ⚠️ UI tree is empty!")
            return False
        
        tl = target.lower().strip()
        if not tl:
            return False
        query_words = set(tl.split())
        
        print(f"   📋 Checking {len(self.ui_analyzer.last_elements)} elements in UI tree...")
        
        # Pass 1: Exact substring match in text
        for elem in self.ui_analyzer.last_elements:
            if elem.text and tl in elem.text.lower():
                self.device.tap(*elem.center)
                time.sleep(0.3)  # Allow UI to respond
                print(f"✅ {elem.text}")
                return True
        
        # Pass 2: Exact substring in content-desc
        for elem in self.ui_analyzer.last_elements:
            if elem.content_desc and tl in elem.content_desc.lower():
                self.device.tap(*elem.center)
                time.sleep(0.3)  # Allow UI to respond
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
            time.sleep(0.3)  # Allow UI to respond
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
            time.sleep(0.3)  # Allow UI to respond
            print(f"✅ {matches[0].text} (OCR)")
            return True
        fuzzy = self.ocr.find_text_fuzzy(screenshot, target, threshold=0.7)
        if fuzzy:
            _, match = fuzzy[0]
            self.device.tap(*match.center)
            time.sleep(0.3)  # Allow UI to respond
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
            x, y = result.coordinates
            
            # Validate coordinates are reasonable
            try:
                w, h = self.device.screen_size()
                
                # Check if coordinates are at edges (likely hallucinations)
                if x < 10 or x > w - 10 or y < 10 or y > h - 10:
                    print(f"   ⚠️ Coordinates at screen edge: ({x}, {y}), likely hallucination")
                    return False
                
                if not (0 <= x <= w and 0 <= y <= h):
                    print(f"❌ Invalid coordinates from vision: ({x}, {y}) - screen: {w}x{h}")
                    return False
                    
            except Exception:
                pass
            
            print(f"🎯 Vision found at ({x}, {y}): {result.description} (confidence: {result.confidence:.0%})")
            self.device.tap(x, y)
            time.sleep(0.5)
            print(f"✅ {result.description} (vision)")
            return True
        
        if result.description and "not" in result.description.lower():
            print(f"   ℹ️ Vision: {result.description}")
        else:
            print(f"❌ Vision couldn't find: {target}")
    
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
