# =========================
# FILE: agent/screen_controller.py
# =========================
"""
Screen controller — v5 PARALLEL RACE.

UI tree + app memory run simultaneously with Gemini vision.
Whichever track finds a valid target first claims the tap (no double-tap).

Flow for "click subscribe":
  Track A (UI tree + app memory)  ┐
                                  ├─ race → first hit wins → tap
  Track B (Gemini vision)         ┘
  OCR remains a last-resort fallback if both tracks miss.
"""

import time
import os
import re
import tempfile
import threading
import concurrent.futures
from typing import Optional, List, Tuple
from agent.adb import AdbClient
from agent.device import DeviceController
from agent.ui_analyzer import UIAnalyzer, UIElement
from agent.ocr_engine import OCREngine
from agent.ollama_vision import OllamaVision, VisionResult, _word_eq
from agent.query_router import QueryRouter, QueryIntent
from agent.app_memory import APP_MEMORY
from agent.screen_inspector import ScreenInspector


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
    # YouTube labels the like control "like this video along with N other
    # people" and flips it to "Unlike" once liked — both must resolve to it.
    "like": ["Like", "Like button", "Heart", "like this video", "Unlike"],
    "unlike": ["Unlike", "Like", "like this video", "Remove like"],
    "dislike": ["Dislike", "Dislike button", "dislike this video", "Undislike"],
    "share": ["Share", "Share button"],
    "subscribe": ["Subscribe", "Subscribe button", "SUBSCRIBE", "Subscribe to"],
    # Same control as Subscribe — YouTube toggles the label, not the widget.
    "unsubscribe": ["Unsubscribe", "Unsubscribe button", "UNSUBSCRIBE",
                    "Subscribed", "Subscribe", "Subscribe to"],
    "skip ad": ["Skip ad", "Skip Ads", "Skip ads", "Skip", "Skip Ad"],
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
        self.vision = OllamaVision()
        self.router = QueryRouter()
        self.app_memory = APP_MEMORY
        self._tap_claim_lock = threading.Lock()
        self._tap_claimed = False

        # Legacy screenshot path (for OCR which needs a file)
        self.screenshot_path = os.path.join(tempfile.gettempdir(), "screenshot.png")
        self.last_screenshot_time = 0
        self.screenshot_cache_duration = 3

        # Parallel pipeline: when True, skip capture_ui_tree in search methods
        # because data was already pre-fetched and injected by parallel.py
        self._prefetch_fresh = False
        self._bg_running = False
        self._bg_thread = None

        try:
            w, h = device.screen_size()
            self.vision.set_screen_size(w, h)
        except Exception:
            pass

        self.gemini = None
        try:
            from agent.gemini_computer_use import GeminiComputerUse
            self.gemini = GeminiComputerUse(device, self.vision)
        except Exception as e:
            print(f"⚠️ Gemini Computer Use unavailable: {e}")

        # Start background UI cache watcher
        self.ui_analyzer.start_cache_watcher()
    
    def mark_prefetch_fresh(self) -> None:
        """Mark that pre-fetched data has been injected (skip next captures)."""
        self._prefetch_fresh = True
    
    def _maybe_capture(self) -> None:
        """Capture UI tree unless pre-fetched or watcher-cached data is fresh."""
        if self._prefetch_fresh:
            # Data was pre-fetched by the parallel pipeline — use it
            return
        cached = self.ui_analyzer.get_cached_elements()
        if cached:
            self.ui_analyzer.last_elements = cached
            return
        self.ui_analyzer.capture_ui_tree(force_refresh=True)
    
    def _consume_prefetch(self) -> None:
        """Reset the prefetch flag after the first query execution."""
        self._prefetch_fresh = False
    
    def start_watching(self) -> None:
        """Start background vision watching (screenshots + semantic screen map)."""
        self.vision.start_watching(self.adb)
        self._bg_running = True
        self._bg_thread = threading.Thread(target=self._prewarm_loop, daemon=True)
        self._bg_thread.start()

    def warm_start(self, wait_vision: bool = True,
                   start_background: bool = True) -> None:
        """
        Prime UI + vision indexes before the first user command.
        Call once at process start so live-index taps have zero cold latency.

        Leave `start_background` off while the rest of startup still needs the
        ADB bus; the watcher's screencap/dump cycle otherwise queues ahead of
        it and adds seconds to app loading.
        """
        # 1) UI tree immediately (feeds live index)
        try:
            print("🔥 Warming UI tree…")
            # Best-effort only: this primes a cache, so neither retrying nor
            # waiting out a stuck dump is worth delaying the prompt for. The
            # first real command captures properly if this comes back empty.
            self.ui_analyzer.capture_ui_tree(
                force_refresh=True, background=False, attempts=1, timeout=6
            )
            elements = self.ui_analyzer.last_elements or []
            if elements:
                self.vision.ingest_ui_elements(elements)
                self._prefetch_fresh = True
                print(f"✅ UI warm ({len(elements)} elements)")
            else:
                print("⚠️ UI warmup empty")
        except Exception as e:
            print(f"⚠️ UI warmup failed: {e}")

        # 2) Vision screenshot + first Gemini map (blocking once)
        if wait_vision:
            try:
                self.vision.warm_start(self.adb)
            except Exception as e:
                print(f"⚠️ Vision warmup failed: {e}")

        # 3) Keep watching in background afterward
        if start_background:
            self.start_watching()

    def stop_watching(self) -> None:
        self._bg_running = False
        self.vision.stop_watching()

    def _prewarm_loop(self) -> None:
        """
        Keep the UI index warm without monopolising ADB.

        A `uiautomator dump` costs ~3s, so dumping on a fixed short interval kept
        the ADB bus busy almost continuously and delayed user commands by seconds.
        We only re-dump when the screenshot shows the screen actually changed —
        except the first cycle, which always dumps.
        """
        last_signature = ""
        last_dump = 0.0
        first = True
        while getattr(self, '_bg_running', False):
            try:
                if getattr(self.vision, "_paused", False):
                    time.sleep(0.25)
                    continue

                # Never start a ~3s dump while a user command needs the bus.
                if self.adb.foreground_pending():
                    time.sleep(0.1)
                    continue

                signature = self.vision.screenshot_signature()
                age = time.time() - last_dump
                changed = bool(signature) and signature != last_signature
                if not first and not changed and age < 15.0:
                    time.sleep(0.5)
                    continue

                # The screen moved, so whatever is cached describes the old one.
                # Drop it before the slow re-dump: a command arriving in between
                # must not be handed a tree for a screen that is already gone.
                if changed:
                    self.ui_analyzer.invalidate_cache()

                # One bounded try in the background loop — it runs again shortly,
                # and holding the ADB lock longer starves user commands.
                self.ui_analyzer.capture_ui_tree(
                    force_refresh=True, background=True, attempts=1, timeout=10
                )
                last_signature = signature or last_signature
                last_dump = time.time()
                first = False

                elements = self.ui_analyzer.last_elements or []
                if elements:
                    self.vision.ingest_ui_elements(elements)
                    self._prefetch_fresh = True
                time.sleep(0.5)
            except Exception:
                time.sleep(1.5)

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
            try:
                items = self.vision.combined_index()
                print(f"🗺️ Live index ({len(items)} items):")
                for it in items[:16]:
                    print(f"   • [{it.get('source')}] {it.get('label')} @ ({it.get('x')},{it.get('y')})")
            except Exception:
                pass
            self._consume_prefetch()
            return True
        
        # Check for ordinal/position queries: "the first post", "second video"
        ordinal_result = self._check_ordinal(target_lower)
        if ordinal_result:
            pos, item_type = ordinal_result
            result = self._find_nth_item_and_tap(pos, item_type)
            self._consume_prefetch()
            return result

        search_text = self._clean_search_query(target_lower)

        # Pause background capture so command ADB isn't fighting the watch thread
        try:
            self.vision.pause_watching()
        except Exception:
            pass

        try:
            # Chrome actions (Subscribe / Like / Share): prefer the real button
            # BEFORE live-index, which otherwise matches "17.3K subscribers".
            chrome_key = self._chrome_action_key(search_text or target_lower)
            if chrome_key:
                self._maybe_capture()
                hit = self._find_chrome_button(chrome_key)
                if hit:
                    x, y, label = hit
                    print(f"⚡ Chrome button: {label}")
                    self._tap_claimed = False
                    ok = self._claim_and_tap(x, y, label, "chrome-btn")
                    self._consume_prefetch()
                    return ok

            # Instant path: use index built while idle (no on-demand analysis)
            mapped = self.vision.find_in_screen_map(search_text or target)
            if mapped.coordinates and mapped.confidence >= 0.55:
                x, y = mapped.coordinates
                if self._coords_sane(x, y):
                    print(f"⚡ Live index hit (no re-analysis): {mapped.description}")
                    self._tap_claimed = False
                    ok = self._claim_and_tap(x, y, mapped.description or target, "live-index")
                    self._consume_prefetch()
                    return ok

            print(f"🔍 Index miss — race UI ⚡ live vision → '{target}' (text: '{search_text}')")

            # Reset claim so only one track can tap
            self._tap_claimed = False

            # Visual / content queries → vision preferred; UI needs strong text match
            vision_preferred = any(w in target_lower for w in VISION_ONLY_WORDS) or self._looks_visual_content(
                search_text or target_lower
            )

            def track_ui() -> bool:
                hit = self._locate_via_ui_and_memory(
                    search_text, target_lower, require_strong=vision_preferred
                )
                if not hit:
                    return False
                x, y, label = hit
                return self._claim_and_tap(x, y, label, "ui+memory")

            def track_vision() -> bool:
                if not self.vision.available:
                    return False
                # Skip map (already tried); go straight to live locate
                hit = self._locate_via_vision(target, skip_map=True)
                if not hit:
                    return False
                x, y, label = hit
                return self._claim_and_tap(x, y, label, "vision")

            workers = [track_ui, track_vision]
            won = False
            pool = concurrent.futures.ThreadPoolExecutor(max_workers=len(workers))
            futures = [pool.submit(fn) for fn in workers]
            try:
                for fut in concurrent.futures.as_completed(futures):
                    try:
                        if fut.result():
                            won = True
                            break
                    except Exception as e:
                        print(f"   ⚠️ Track error: {e}")
            finally:
                pool.shutdown(wait=False, cancel_futures=True)

            if won:
                self._consume_prefetch()
                return True

            # Gemini Computer Use — sees the screen and taps what you named
            if self.gemini and getattr(self.gemini, "available", False):
                print(f"✨ Gemini Computer Use → '{target}'")
                g = self.gemini.find_and_tap(target)
                if g.ok:
                    print(f"✅ Gemini: {', '.join(g.actions) or g.message}")
                    self._consume_prefetch()
                    return True
                print(f"   ℹ️ Gemini miss: {g.message}")

            if self.ocr.available and self._try_ocr_search(search_text):
                self._consume_prefetch()
                return True

            self._consume_prefetch()
            print(f"❌ Not found: {target}")
            return False
        finally:
            try:
                self.vision.resume_watching()
            except Exception:
                pass

    def _looks_visual_content(self, text: str) -> bool:
        """True when the query likely refers to image/post content, not a chrome button."""
        t = (text or "").lower()
        chrome = {
            "subscribe", "unsubscribe", "like", "share", "search", "home",
            "back", "menu", "settings", "send", "follow", "profile",
        }
        if t in chrome or any(t == c or t.startswith(c + " ") for c in chrome):
            return False
        # Multi-word content ("penguin post", "hungry wolf") or non-chrome nouns
        return len(t.split()) >= 1 and t not in chrome

    def _claim_and_tap(self, x: int, y: int, label: str, source: str) -> bool:
        """First successful track wins; later tracks are ignored (no double-tap)."""
        with self._tap_claim_lock:
            if self._tap_claimed:
                print(f"   ⏭️ Skipping late {source} hit (already tapped)")
                return False
            self._tap_claimed = True
        print(f"🎯 Race winner [{source}] at ({x}, {y}): {label}")
        self.device.tap(x, y)
        time.sleep(0.3)
        print(f"✅ {label} ({source})")
        return True

    def _current_package(self) -> str:
        elements = self.ui_analyzer.last_elements or []
        packages = [e.package for e in elements if e.package]
        if not packages:
            return ""
        return max(set(packages), key=packages.count)

    # Toggle controls keep one label regardless of state, so the "off" verb has
    # to be allowed to match the "on" label (Unlike -> the Like button).
    _TOGGLE_SYNONYMS = {
        "unlike": ("like",),
        "unsubscribe": ("subscribe", "subscribed"),
        "unfollow": ("follow", "following"),
        "undislike": ("dislike",),
        "unmute": ("mute",),
    }

    def _strong_token_hit(self, query: str, label: str) -> bool:
        """Require a meaningful query token to appear in the UI label."""
        stop = {
            "the", "a", "an", "on", "to", "of", "and", "or", "post", "pin",
            "item", "card", "video", "photo", "picture", "image", "button",
        }
        q = (query or "").lower().replace("'", " ").replace("’", " ")
        tokens = [t for t in q.split() if len(t) > 2 and t not in stop]
        if not tokens:
            tokens = [t for t in q.split() if len(t) > 2]
        for tok in list(tokens):
            tokens.extend(self._TOGGLE_SYNONYMS.get(tok, ()))
        lab = (label or "").lower()
        return any(tok in lab for tok in tokens)

    def _locate_via_ui_and_memory(
        self, search_text: str, target_lower: str, require_strong: bool = False
    ) -> Optional[Tuple[int, int, str]]:
        """
        Track A: app memory + knowledge base + UI tree + brute-force text.
        Returns (x, y, label) without tapping.
        When require_strong=True, reject matches that don't contain query tokens
        (stops weak brute-force from stealing visual queries like 'penguin post').
        """
        self._maybe_capture()
        elements = self.ui_analyzer.last_elements or []
        if not elements:
            print("   ⚠️ UI tree empty (Track A)")
            return None

        package = self._current_package()
        query_for_match = search_text or target_lower

        def _accept(hit: Optional[Tuple[int, int, str]], source: str):
            if not hit:
                return None
            x, y, label = hit
            if require_strong and not self._strong_token_hit(query_for_match, label):
                print(f"   ⛔ Weak UI match rejected ({source}): '{label}'")
                return None
            return hit

        # 1) App memory (resource IDs / known descriptors)
        mem_elem = self.app_memory.resolve_in_elements(package, query_for_match, elements)
        if mem_elem is not None:
            label = mem_elem.text or mem_elem.content_desc or mem_elem.resource_id or search_text
            hit = _accept((*mem_elem.center, label), "memory")
            if hit:
                print(f"   🧠 App memory matched: {label}")
                return hit

        # 1b) ScreenInspector for search intents
        if "search" in query_for_match:
            search_el = ScreenInspector.find_search_target(elements)
            if search_el is not None:
                label = search_el.text or search_el.content_desc or "search"
                hit = _accept((*search_el.center, label), "inspector")
                if hit:
                    print(f"   🧭 ScreenInspector search: {label}")
                    return hit

        # 2) Content-desc knowledge base
        hit = _accept(self._find_content_desc_match(query_for_match), "knowledge")
        if hit:
            return hit

        # 3) UI tree smart search
        hit = _accept(self._find_ui_tree_match(query_for_match), "ui-tree")
        if hit:
            return hit

        # 4) Brute-force scoring (high bar when visual content)
        hit = self._find_brute_force_match(target_lower, min_priority=25 if require_strong else 15)
        hit = _accept(hit, "brute")
        if hit:
            return hit

        print("   ℹ️ Track A (UI+memory) miss")
        return None

    def _locate_via_vision(
        self, target: str, skip_map: bool = False
    ) -> Optional[Tuple[int, int, str]]:
        """Track B: live index (optional) then Gemini vision locate. Returns (x, y, label)."""
        if not skip_map:
            mapped = self.vision.find_in_screen_map(target)
            if mapped.coordinates and mapped.confidence >= 0.55:
                x, y = mapped.coordinates
                if self._coords_sane(x, y):
                    print(f"   🗺️ Screen-map hit: {mapped.description}")
                    return (x, y, mapped.description or target)

        # Live API locate (uses cached screenshot; does not re-check map)
        b64 = self.vision.capture_screenshot_b64()
        if b64:
            result = self.vision.find_element(b64, target, is_b64=True)
            if result.coordinates and result.confidence > 0.4:
                x, y = result.coordinates
                if self._coords_sane(x, y):
                    return (x, y, result.description or target)

        print("   ℹ️ Live vision miss, trying icon appearance...")
        icon_result = self.vision.find_icon_by_appearance(f"a button or icon for '{target}'")
        if icon_result.coordinates and icon_result.confidence > 0.4:
            x, y = icon_result.coordinates
            if self._coords_sane(x, y):
                return (x, y, icon_result.description or target)

        print("   ℹ️ Track B (vision) miss")
        return None

    def _coords_sane(self, x: int, y: int) -> bool:
        try:
            w, h = self.device.screen_size()
            if x < 10 or x > w - 10 or y < 10 or y > h - 10:
                print(f"   ⚠️ Coordinates at screen edge: ({x}, {y}), likely hallucination")
                return False
            if not (0 <= x <= w and 0 <= y <= h):
                print(f"   ❌ Invalid coordinates: ({x}, {y}) screen: {w}x{h}")
                return False
        except Exception:
            pass
        return True

    def _chrome_action_key(self, text: str) -> str:
        """Return canonical chrome action if the query is Subscribe/Like/Share/etc.

        Longest keys are tested first so 'unlike' and 'unsubscribe' aren't
        swallowed by 'like' / 'subscribe'.
        """
        t = (text or "").lower().strip()
        keys = (
            "skip ad", "skip advertisement", "unsubscribe", "unfollow",
            "undislike", "dislike", "unlike", "subscribe", "like", "share",
            "follow", "comment", "save", "download",
        )
        for k in sorted(keys, key=len, reverse=True):
            if t == k or t.startswith(k + " ") or f" {k} " in f" {t} ":
                return "skip ad" if k.startswith("skip ad") else k
        return ""

    # Stat labels that merely mention the action ("59.3K subscribers").
    _COUNT_LABEL = re.compile(
        r'\b[\d.,]+\s*[kmb]?\s*(subscribers?|likes?|followers?|views?|comments?)\b',
        re.I,
    )

    @staticmethod
    def _label_starts_with_action(label: str, word: str) -> bool:
        """True for 'Subscribe to X' / 'Like this video…' style button labels."""
        if not label or not word:
            return False
        return bool(re.match(rf'\s*{re.escape(word)}\b', label.strip(), re.I))

    def _find_chrome_button(self, action: str) -> Optional[Tuple[int, int, str]]:
        """
        Find the real action button (e.g. Subscribe), not related text like
        '59.3K subscribers' or 'I like this' when the action is ambiguous.

        Real buttons are often verbose — YouTube labels them 'Subscribe to
        <channel>.' and 'like this video along with 4,180 other people' — so
        matching cannot depend on the label being short.
        """
        elements = self.ui_analyzer.last_elements or []
        if not elements:
            return None

        action = (action or "").lower().strip()
        known = UI_ELEMENT_KNOWLEDGE.get(action, [action])
        variants = [v.lower() for v in known] + [action]
        # Toggles share one control: "unlike" is the Like button in liked state.
        id_needles = {v.replace(" ", "_") for v in variants if v}
        id_needles |= {f"{n}_button" for n in list(id_needles)}

        # Labels that contain the word but are NOT the button
        reject_substrings = {
            "subscribe": ("subscriber count", "thousand subscribers"),
            "follow": ("following",),
            "share": ("shared",),
        }.get(action, ())

        id_hits, exact_hits, prefix_hits, soft_hits = [], [], [], []
        for elem in elements:
            if not elem.clickable and "Button" not in (elem.class_name or ""):
                continue
            text = (elem.text or "").lower().strip()
            desc = (elem.content_desc or "").lower().strip()
            rid = (elem.resource_id or "").lower()
            label = text or desc
            combined = f"{text} {desc} {rid}"

            # A subscriber/like count is never the control itself.
            if label and self._COUNT_LABEL.search(label):
                continue
            if reject_substrings and any(r in combined for r in reject_substrings):
                continue

            rid_tail = rid.split("/")[-1] if rid else ""
            if rid_tail and any(n == rid_tail or n in rid_tail for n in id_needles):
                id_hits.append(elem)
                continue

            if text == action or desc == action or any(
                text == v or desc == v for v in variants
            ):
                exact_hits.append(elem)
                continue

            if any(self._label_starts_with_action(label, v) for v in variants):
                prefix_hits.append(elem)
                continue

            if label and len(label) <= 24:
                for v in variants:
                    if _word_eq(label, v) or _word_eq(desc, v):
                        soft_hits.append(elem)
                        break

        for bucket in (id_hits, exact_hits, prefix_hits, soft_hits):
            if bucket:
                pick = bucket[0]
                label = pick.text or pick.content_desc or action
                return (*pick.center, label)
        return None

    def _find_content_desc_match(self, target_lower: str) -> Optional[Tuple[int, int, str]]:
        chrome = self._chrome_action_key(target_lower)
        if chrome:
            return self._find_chrome_button(chrome)

        known = UI_ELEMENT_KNOWLEDGE.get(target_lower)
        if not known:
            for key, descs in UI_ELEMENT_KNOWLEDGE.items():
                if key in target_lower or target_lower in key:
                    known = descs
                    break
        if not known or not self.ui_analyzer.last_elements:
            return None

        for elem in self.ui_analyzer.last_elements:
            if not elem.clickable and "Button" not in elem.class_name:
                continue
            desc = elem.content_desc.lower()
            text = (elem.text or "").lower()
            for variant in known:
                variant_lower = variant.lower()
                if text == variant_lower or desc == variant_lower:
                    label = elem.text or elem.content_desc
                    return (*elem.center, label)
                if _word_eq(desc, variant_lower) or _word_eq(text, variant_lower):
                    label = elem.text or elem.content_desc
                    return (*elem.center, label)
        return None

    def _find_ui_tree_match(self, target: str) -> Optional[Tuple[int, int, str]]:
        if not self.ui_analyzer.last_elements:
            return None
        tl = target.lower().strip()
        if not tl:
            return None
        query_words = set(tl.split())

        for elem in self.ui_analyzer.last_elements:
            if elem.text and tl in elem.text.lower():
                return (*elem.center, elem.text)
        for elem in self.ui_analyzer.last_elements:
            if elem.content_desc and tl in elem.content_desc.lower():
                return (*elem.center, elem.content_desc)

        best_elem = None
        best_score = 0.0
        for elem in self.ui_analyzer.last_elements:
            text = (elem.text or "").lower()
            desc = (elem.content_desc or "").lower()
            combined = text + " " + desc
            if not combined.strip():
                continue
            overlap = query_words & set(combined.split())
            if len(overlap) < 1:
                continue
            score = len(overlap) / len(query_words)
            if len(text) > 20:
                score += 0.1
            if elem.clickable:
                score += 0.05
            if score > best_score:
                best_score = score
                best_elem = elem
        if best_elem and best_score >= 0.5:
            label = best_elem.text or best_elem.content_desc
            return (*best_elem.center, label)
        return None

    def _find_brute_force_match(
        self, target: str, min_priority: int = 15
    ) -> Optional[Tuple[int, int, str]]:
        if not self.ui_analyzer.last_elements:
            return None
        target_lower = target.lower().replace("'", " ").replace("’", " ")
        target_words = set(target_lower.split())
        stop = {"a", "the", "an", "to", "of", "on", "and", "or", "post", "pin", "item"}
        high_priority_keywords = {
            "subscribe": 50, "unsubscribe": 50, "follow": 45,
            "unfollow": 45, "like": 40, "share": 40,
        }
        candidates = []
        for elem in self.ui_analyzer.last_elements:
            text = (elem.text or "").lower().strip()
            desc = (elem.content_desc or "").lower().strip()
            resource = (elem.resource_id or "").lower()
            if not (text or desc):
                continue
            combined = f"{text} {desc} {resource}"
            priority = 0
            for keyword, boost in high_priority_keywords.items():
                if keyword in combined:
                    priority += boost
                    break
            if text == target_lower or desc == target_lower:
                priority += 20
            if target_lower in text or target_lower in desc or target_lower in resource:
                priority += 15
            combined_words = set(text.split()) | set(desc.split())
            word_overlap = 0
            for tw in target_words:
                if tw in stop or len(tw) < 3:
                    continue
                # Exact token match only — avoid "post" ⊂ "promoted" style false hits
                if tw in combined_words:
                    word_overlap += 1
                elif any(tw == ew or (len(tw) >= 4 and (tw in ew or ew in tw)) for ew in combined_words):
                    word_overlap += 1
            if word_overlap:
                priority += word_overlap * 5
            first = next((w for w in target_lower.split() if w not in stop and len(w) > 2), "")
            if first and (text.startswith(first) or desc.startswith(first)):
                priority += 8
            if elem.clickable:
                priority += 3
            if "Button" in elem.class_name:
                priority += 2
            if priority >= min_priority:
                candidates.append((priority, elem))
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0], reverse=True)
        best_priority, best_elem = candidates[0]
        label = best_elem.text or best_elem.content_desc
        print(f"   🎯 Brute-force best: '{label}' (priority: {best_priority})")
        try:
            w, h = self.device.screen_size()
            x, y = best_elem.center
            if not (0 < x < w and 0 < y < h):
                return None
        except Exception:
            pass
        return (*best_elem.center, label)
    
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
        """Race UI-list detection vs vision for ordinal queries."""
        print(f"🎯 Finding #{position} {item_type} (parallel race)...")
        self._tap_claimed = False

        def track_ui() -> bool:
            items = self._find_items_ui(item_type)
            if not items:
                return False
            idx = position - 1 if position > 0 else position
            if position > 0 and not (0 <= idx < len(items)):
                return False
            if position < 0 and len(items) < abs(idx):
                return False
            elem = items[idx]
            label = elem.text or elem.content_desc or elem.class_name
            return self._claim_and_tap(*elem.center, f"#{position} {item_type}: {label}", "ui")

        def track_vision() -> bool:
            if not self.vision.available:
                return False
            ords = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth"}
            ordinal_word = ords.get(position, f"{position}th")
            result = self.vision.find_element_fast(f"the {ordinal_word} {item_type}")
            if result.coordinates and result.confidence > 0.4:
                x, y = result.coordinates
                if self._coords_sane(x, y):
                    return self._claim_and_tap(x, y, f"#{position} {item_type}", "vision")
            return False

        pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        futures = [pool.submit(track_ui), pool.submit(track_vision)]
        try:
            for fut in concurrent.futures.as_completed(futures):
                try:
                    if fut.result():
                        return True
                except Exception as e:
                    print(f"   ⚠️ Ordinal track error: {e}")
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        print(f"❌ Could not find #{position} {item_type}")
        return False

    # =========================================================
    # Strategy 1: Content-desc knowledge (fast path) — tap variants
    # =========================================================
    def _try_content_desc(self, target_lower: str) -> bool:
        """Check if target is in knowledge base and find it on screen."""
        hit = self._find_content_desc_match(target_lower)
        if not hit:
            # Ensure tree is captured for legacy callers
            self._maybe_capture()
            hit = self._find_content_desc_match(target_lower)
        if not hit:
            return False
        x, y, label = hit
        print(f"   ✅ Found in knowledge base: {label}")
        self.device.tap(x, y)
        time.sleep(0.3)
        print(f"✅ {label}")
        return True

    def _brute_force_text_search(self, target: str) -> bool:
        """
        Last-resort search: look for ANY clickable element containing target text.
        """
        self._maybe_capture()
        hit = self._find_brute_force_match(target)
        if not hit:
            print(f"   ℹ️ No matching elements for '{target}'")
            return False
        x, y, label = hit
        print(f"   📍 Tapping at ({x}, {y})")
        self.device.tap(x, y)
        time.sleep(0.5)
        print(f"✅ {label}")
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
        self._maybe_capture()
        if not self.ui_analyzer.last_elements:
            print(f"   ⚠️ UI tree empty!")
            return False
        print(f"   📋 Checking {len(self.ui_analyzer.last_elements)} elements in UI tree...")
        hit = self._find_ui_tree_match(target)
        if not hit:
            return False
        x, y, label = hit
        self.device.tap(x, y)
        time.sleep(0.3)
        print(f"✅ {label}")
        return True

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
        """Use vision model. Tries text-based search first, then icon-based."""
        hit = self._locate_via_vision(target)
        if not hit:
            print(f"❌ Vision couldn't find: {target}")
            return False
        x, y, label = hit
        print(f"🎯 Vision found at ({x}, {y}): {label}")
        self.device.tap(x, y)
        time.sleep(0.5)
        print(f"✅ {label} (vision)")
        return True
    
    def _vision_find_and_tap(self, target: str) -> bool:
        """Legacy: capture + find. Use _fast version when possible."""
        return self._vision_find_and_tap_fast(target)

    # =========================================================
    # INFO
    # =========================================================
    def _execute_info(self, intent: QueryIntent) -> bool:
        # Prefer live index built while watching (no wait for new vision call)
        cached = ""
        try:
            cached = self.vision.cached_screen_summary()
        except Exception:
            pass
        if cached:
            print(f"\n🖼️ {cached}")
            print()
            return True

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
        # A dump costs ~2.9s; reuse the prefetched/watcher tree when it's fresh.
        self._maybe_capture()
        
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
