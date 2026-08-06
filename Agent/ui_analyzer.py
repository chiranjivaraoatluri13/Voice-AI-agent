# =========================
# FILE: agent/ui_analyzer.py
# =========================
"""
UI Automator wrapper for fast element detection.
Parses XML hierarchy and finds elements by text, ID, class, etc.
"""

import xml.etree.ElementTree as ET
from typing import List, Optional, Tuple
from dataclasses import dataclass, field
from agent.adb import AdbClient
import threading
import time


@dataclass
class UIElement:
    """Represents a UI element from the accessibility tree"""
    
    text: str
    resource_id: str
    class_name: str
    package: str
    content_desc: str
    bounds: Tuple[int, int, int, int]  # (left, top, right, bottom)
    clickable: bool
    scrollable: bool
    checkable: bool
    checked: bool
    
    # HIERARCHICAL TRACKING (NEW)
    parent_index: Optional[int] = None       # Index of parent element in list
    depth: int = 0                            # Depth in hierarchy (root=0)
    path: str = ""                            # Path like "Frame > CardView > Button"
    
    @property
    def center(self) -> Tuple[int, int]:
        """Get center coordinates for tapping"""
        left, top, right, bottom = self.bounds
        return ((left + right) // 2, (top + bottom) // 2)
    
    @property
    def width(self) -> int:
        return self.bounds[2] - self.bounds[0]
    
    @property
    def height(self) -> int:
        return self.bounds[3] - self.bounds[1]
    
    def is_visible(self) -> bool:
        """Check if element has non-zero bounds (might be visible)"""
        return self.bounds != (0, 0, 0, 0)
    
    def is_interactable(self) -> bool:
        """Check if element is potentially interactable"""
        return self.clickable or self.checkable or self.scrollable
    
    def __repr__(self) -> str:
        return (f"UIElement(text='{self.text}', id='{self.resource_id}', "
                f"class='{self.class_name}', bounds={self.bounds}, depth={self.depth})")


class UIAnalyzer:
    """
    Fast UI tree analysis using Android's UI Automator.
    Includes background caching thread for continuous updates.
    """
    
    def __init__(self, adb: AdbClient) -> None:
        self.adb = adb
        self.last_tree: Optional[ET.Element] = None
        self.last_elements: List[UIElement] = []
        # True when last_elements came from cache because a dump failed.
        self.tree_is_stale = False
        
        # Background caching system
        self._cache_thread: Optional[threading.Thread] = None
        self._cache_lock = threading.Lock()
        self._cache_running = False
        self._cached_elements: List[UIElement] = []
        self._cache_timestamp = 0
        self._cache_generation = -1
        # Validity is driven by change detection, not by this timer: our own
        # taps bump adb.screen_generation, and the watcher calls
        # invalidate_cache() when it sees the screen move on its own. The TTL is
        # only a backstop for changes nobody observed (the user touching the
        # tablet) — at 6s it expired while the screen was still static and
        # charged every command a needless ~3s re-dump.
        self._cache_ttl = 12.0
    
    # -------------------------
    # Background Cache Watcher
    # -------------------------
    def start_cache_watcher(self) -> None:
        """Start background thread that continuously updates UI cache."""
        # Disabled: Background cache was causing latency issues
        try:
            print("✅ UI cache system ready (on-demand mode)")
        except UnicodeEncodeError:
            print("[UI Analyzer] UI cache system ready (on-demand mode)")
    
    def stop_cache_watcher(self) -> None:
        """Stop background cache watcher thread."""
        self._cache_running = False
        if self._cache_thread:
            self._cache_thread.join(timeout=0.5)
            self._cache_thread = None
    
    def _cache_watcher_loop(self) -> None:
        """Disabled: Background thread loop removed for performance."""
        pass
    
    def get_cached_elements(self) -> List[UIElement]:
        """Return cached elements when still known to describe the screen."""
        with self._cache_lock:
            if not self._cached_elements:
                return []
            # We tapped/launched something since this tree was captured, so it
            # describes the previous screen.
            if getattr(self.adb, "screen_generation", 0) != self._cache_generation:
                return []
            if (time.time() - self._cache_timestamp) > self._cache_ttl:
                return []
            return self._cached_elements.copy()

    def invalidate_cache(self) -> None:
        """Drop the cached tree because the screen is known to have changed."""
        with self._cache_lock:
            self._cached_elements = []
            self._cache_timestamp = 0.0
            self._cache_generation = -1

    def cache_age(self) -> float:
        with self._cache_lock:
            if not self._cached_elements:
                return 1e9
            return time.time() - self._cache_timestamp
    
    def dump_screen_elements(self) -> str:
        """Dump all screen elements as human-readable text for debugging."""
        with self._cache_lock:
            elements = self._cached_elements.copy()
            age = time.time() - self._cache_timestamp
        
        if not elements:
            return f"❌ No cached elements (cache age: {age:.1f}s)"
        
        output = [f"📱 Screen Elements ({len(elements)} total, cache age: {age:.1f}s):"]
        clickable = [e for e in elements if e.clickable or "Button" in e.class_name]
        output.append(f"🔘 Clickable/Button: {len(clickable)}")
        
        for i, elem in enumerate(clickable[:25], 1):
            text = elem.text or elem.content_desc or "[empty]"
            text = text[:45]
            status = "✓" if "subscribe" in text.lower() or "unsubscribe" in text.lower() else " "
            output.append(f"  {status} {i:2d}. {text:45s} | {elem.class_name}")
        
        if len(clickable) > 25:
            output.append(f"  ... and {len(clickable) - 25} more")
        
        return "\n".join(output)
    
    # -------------------------
    # UI Hierarchy Capture
    # -------------------------
    def capture_ui_tree(self, force_refresh: bool = False,
                        background: bool = False, attempts: int = 3,
                        timeout: Optional[int] = None) -> None:
        """
        Capture current UI hierarchy from device.
        Cached by default unless force_refresh=True.
        """
        if not force_refresh:
            cached = self.get_cached_elements()
            if cached:
                self.last_elements = cached
                return
        
        # Sample before dumping: an action landing mid-dump means the resulting
        # tree may already describe the previous screen.
        generation = getattr(self.adb, "screen_generation", 0)
        try:
            xml_content = self._dump_xml(background=background, attempts=attempts,
                                         timeout=timeout)

            if not xml_content:
                # Fallback to cache if capture fails
                cached = self.get_cached_elements()
                if cached:
                    self.last_elements = cached
                    self.tree_is_stale = True
                    return
                self.last_elements = []
                return

            self.tree_is_stale = False
            
            # Parse XML
            self.last_tree = ET.fromstring(xml_content)
            
            # Parse all elements
            self.last_elements = self._parse_tree(self.last_tree)
            
            # Update cache
            with self._cache_lock:
                self._cached_elements = self.last_elements.copy()
                self._cache_timestamp = time.time()
                self._cache_generation = generation
            
        except Exception as e:
            # Fallback to cache on error
            cached = self.get_cached_elements()
            if cached:
                self.last_elements = cached
                self.tree_is_stale = True
            else:
                self.last_tree = None
                self.last_elements = []

    DUMP_PATH = "/sdcard/ui_dump.xml"
    # A settled screen dumps in ~3s, but an animating overlay (notification
    # shade, video) can legitimately take ~9s. Cutting those off only wasted the
    # work and forced a retry, so allow headroom while still bounding a stuck
    # uiautomator well short of adb's 30s default.
    DUMP_TIMEOUT_S = 15
    DUMP_BUDGET_S = 18.0

    def _dump_xml(self, background: bool = False, attempts: int = 3,
                  timeout: Optional[int] = None) -> str:
        """
        Dump the window hierarchy, retrying when the window won't go idle.

        While a video or ad plays, uiautomator succeeds only ~half the time —
        it either reports "could not get idle state", gets Killed, or hangs —
        and it leaves the previous dump file in place on failure. Blindly
        `cat`-ing that file returned a completely different screen, which is
        why like / subscribe silently resolved against the stale feed.
        """
        per_try = timeout or self.DUMP_TIMEOUT_S
        deadline = time.time() + self.DUMP_BUDGET_S
        for attempt in range(attempts):
            try:
                out = self.adb.run(
                    ["shell", "uiautomator", "dump", self.DUMP_PATH],
                    timeout=per_try,
                    background=background,
                ) or ""
            except Exception:
                out = ""

            # AOSP's success line is "UI hierchary dumped to: <path>" (sic).
            if "dumped to" in out.lower():
                try:
                    xml = self.adb.run_binary(
                        ["shell", "cat", self.DUMP_PATH],
                        timeout=per_try, background=background,
                    ).decode("utf-8", errors="ignore")
                except Exception:
                    xml = ""
                if xml and "<hierarchy" in xml:
                    return xml

            if attempt >= attempts - 1 or time.time() >= deadline:
                break
            time.sleep(0.4)

        return ""

    
    def _parse_tree(self, root: ET.Element) -> List[UIElement]:
        """Recursively parse XML tree into UIElement objects.

        Populates hierarchy metadata (parent_index, depth, path) so that
        find_children_of / find_descendants_of / breadcrumb helpers and the
        UITreeNavigator can actually traverse the tree.
        """
        elements: List[UIElement] = []

        def parse_node(node: ET.Element, parent_index: Optional[int], depth: int,
                       parent_path: str):
            # Parse bounds: "[x1,y1][x2,y2]" -> (x1, y1, x2, y2)
            bounds_str = node.get("bounds", "[0,0][0,0]")
            bounds = self._parse_bounds(bounds_str)

            element = UIElement(
                text=node.get("text", ""),
                resource_id=node.get("resource-id", ""),
                class_name=node.get("class", ""),
                package=node.get("package", ""),
                content_desc=node.get("content-desc", ""),
                bounds=bounds,
                clickable=node.get("clickable", "false") == "true",
                scrollable=node.get("scrollable", "false") == "true",
                checkable=node.get("checkable", "false") == "true",
                checked=node.get("checked", "false") == "true",
                parent_index=parent_index,
                depth=depth,
            )

            my_index = len(elements)
            elements.append(element)

            # Build a readable path label for this node
            label = (
                element.text
                or (element.resource_id.split("/")[-1] if element.resource_id else "")
                or (element.class_name.split(".")[-1] if element.class_name else "node")
            )
            element.path = f"{parent_path} > {label}" if parent_path else label

            # Recurse children
            for child in node:
                parse_node(child, my_index, depth + 1, element.path)

        parse_node(root, None, 0, "")
        return elements
    
    @staticmethod
    def _parse_bounds(bounds_str: str) -> Tuple[int, int, int, int]:
        """Parse bounds string "[x1,y1][x2,y2]" to (x1, y1, x2, y2)"""
        try:
            # Remove brackets and split
            coords = bounds_str.replace("][", ",").replace("[", "").replace("]", "")
            x1, y1, x2, y2 = map(int, coords.split(","))
            return (x1, y1, x2, y2)
        except Exception:
            return (0, 0, 0, 0)
    
    # -------------------------
    # Hierarchy Navigation
    # -------------------------
    def find_children_of(self, parent_element: UIElement) -> List[UIElement]:
        """Find all direct children of an element"""
        try:
            parent_idx = self.last_elements.index(parent_element)
            return [e for e in self.last_elements if e.parent_index == parent_idx]
        except (ValueError, AttributeError):
            return []
    
    def find_descendants_of(self, parent_element: UIElement) -> List[UIElement]:
        """Find all descendants (children, grandchildren, etc.) of an element"""
        try:
            parent_idx = self.last_elements.index(parent_element)
        except (ValueError, AttributeError):
            return []
        
        descendants = []
        
        def collect_descendants(elem_idx):
            for e in self.last_elements:
                if hasattr(e, 'parent_index') and e.parent_index == elem_idx:
                    descendants.append(e)
                    collect_descendants(self.last_elements.index(e))
        
        collect_descendants(parent_idx)
        return descendants
    
    def get_breadcrumb_to_element(self, element: UIElement) -> List[UIElement]:
        """Get the path from root to this element"""
        try:
            breadcrumb = [element]
            current = element
            
            while hasattr(current, 'parent_index') and current.parent_index is not None and current.parent_index >= 0:
                parent = self.last_elements[current.parent_index]
                breadcrumb.insert(0, parent)
                current = parent
            
            return breadcrumb
        except (ValueError, IndexError, AttributeError):
            return [element]
    
    # -------------------------
    # Element Search Methods
    # -------------------------
    def find_by_text(self, text: str, exact: bool = False) -> List[UIElement]:
        """
        Find elements by text content.
        
        Args:
            text: Text to search for
            exact: If True, match exactly; if False, match substring
        """
        self.capture_ui_tree()
        
        results = []
        text_lower = text.lower()
        
        for elem in self.last_elements:
            if not elem.text:
                continue
            
            if exact:
                if elem.text == text:
                    results.append(elem)
            else:
                if text_lower in elem.text.lower():
                    results.append(elem)
        
        return results
    
    def find_by_id(self, resource_id: str) -> List[UIElement]:
        """Find elements by resource ID"""
        self.capture_ui_tree()
        
        return [elem for elem in self.last_elements 
                if resource_id in elem.resource_id]
    
    def find_by_class(self, class_name: str) -> List[UIElement]:
        """Find elements by class name"""
        self.capture_ui_tree()
        
        return [elem for elem in self.last_elements 
                if class_name in elem.class_name]
    
    def find_by_description(self, desc: str) -> List[UIElement]:
        """Find elements by content description"""
        self.capture_ui_tree()
        
        desc_lower = desc.lower()
        return [elem for elem in self.last_elements 
                if desc_lower in elem.content_desc.lower()]
    
    def find_clickable(self) -> List[UIElement]:
        """Find all clickable elements"""
        self.capture_ui_tree()
        
        return [elem for elem in self.last_elements if elem.clickable]
    
    def find_scrollable(self) -> List[UIElement]:
        """Find all scrollable containers"""
        self.capture_ui_tree()
        
        return [elem for elem in self.last_elements if elem.scrollable]
    
    # -------------------------
    # Smart Search
    # -------------------------
    def search(self, query: str) -> List[UIElement]:
        """
        Smart search across text, ID, and description.
        Returns ranked results.
        
        Scoring priorities:
          1. Exact text match (100)
          2. Text starts with query / query starts text (70)
          3. Description starts with query — action buttons like "Subscribe to..." (60)
          4. Text contains query as substring (50)
          5. Description contains query (30), but penalize partial word matches
          6. Resource ID match (20)
          7. Clickable bonus (10)
          8. Smaller elements preferred over large containers (-5 for huge elements)
        """
        self.capture_ui_tree()
        
        query_lower = query.lower()
        scored_results = []
        
        for elem in self.last_elements:
            score = 0
            
            text_lower = (elem.text or "").lower()
            desc_lower = (elem.content_desc or "").lower()
            rid_lower = (elem.resource_id or "").lower()
            
            # --- Text scoring ---
            if text_lower:
                if text_lower == query_lower:
                    # Exact text match (highest)
                    score += 100
                elif text_lower.startswith(query_lower) or query_lower.startswith(text_lower):
                    # Text starts with query or vice versa
                    score += 70
                elif query_lower in text_lower:
                    # Substring match — but check if it's a whole word
                    # "subscribe" in "subscribers" is partial → lower score
                    if self._is_word_match(query_lower, text_lower):
                        score += 50
                    else:
                        score += 25  # partial word match penalty
            
            # --- Content description scoring ---
            if desc_lower and query_lower in desc_lower:
                if desc_lower.startswith(query_lower):
                    # Description STARTS with query → this is an action button
                    # "Subscribe to Sun NXT Telugu." → high priority
                    score += 60
                elif self._is_word_match(query_lower, desc_lower):
                    # Whole word match in description
                    score += 30
                else:
                    # Partial match: "subscribers" contains "subscribe"
                    score += 15
            
            # --- Resource ID scoring ---
            if rid_lower and query_lower in rid_lower:
                score += 20
            
            # --- Clickable bonus ---
            if elem.clickable and score > 0:
                score += 10
            
            # --- Size penalty: prefer focused elements over huge containers ---
            if score > 0:
                area = elem.width * elem.height
                if area > 500000:  # very large element (probably a container)
                    score -= 5
                if elem.width < 50 or elem.height < 50:
                    score -= 5  # too tiny, probably not a real button
            
            if score > 0:
                scored_results.append((score, elem))
        
        # Sort by score descending
        scored_results.sort(key=lambda x: x[0], reverse=True)
        
        return [elem for score, elem in scored_results]
    
    @staticmethod
    def _is_word_match(query: str, text: str) -> bool:
        """Check if query appears as a whole word in text, not as part of another word."""
        import re
        return bool(re.search(r'\b' + re.escape(query) + r'\b', text))
    
    # -------------------------
    # Position-based queries
    # -------------------------
    def find_top_n(self, class_name: str, n: int = 1) -> List[UIElement]:
        """
        Find top N elements of a class (sorted by Y position).
        Useful for "first video", "second item", etc.
        """
        elements = self.find_by_class(class_name)
        
        # Sort by vertical position (top to bottom)
        elements.sort(key=lambda e: e.bounds[1])
        
        return elements[:n]
    
    def find_in_region(
        self, 
        region: str, 
        class_name: Optional[str] = None
    ) -> List[UIElement]:
        """
        Find elements in a screen region: 'top', 'bottom', 'left', 'right', 'center'
        """
        self.capture_ui_tree()
        
        # Get screen bounds from root
        if not self.last_elements:
            return []
        
        # Assume screen is largest element
        max_x = max(elem.bounds[2] for elem in self.last_elements)
        max_y = max(elem.bounds[3] for elem in self.last_elements)
        
        # Define regions
        regions = {
            "top": lambda e: e.bounds[1] < max_y * 0.25,
            "bottom": lambda e: e.bounds[1] > max_y * 0.75,
            "left": lambda e: e.bounds[0] < max_x * 0.25,
            "right": lambda e: e.bounds[0] > max_x * 0.75,
            "center": lambda e: (
                max_x * 0.25 < e.bounds[0] < max_x * 0.75 and
                max_y * 0.25 < e.bounds[1] < max_y * 0.75
            ),
        }
        
        filter_func = regions.get(region.lower())
        if not filter_func:
            return []
        
        results = [elem for elem in self.last_elements if filter_func(elem)]
        
        # Filter by class if specified
        if class_name:
            results = [e for e in results if class_name in e.class_name]
        
        return results
    
    # -------------------------
    # Information Extraction
    # -------------------------
    def describe_screen(self) -> str:
        """
        Generate a text description of the current screen.
        """
        self.capture_ui_tree()
        
        if not self.last_elements:
            return "Unable to analyze screen (UI tree empty)"
        
        # Get app package
        packages = set(elem.package for elem in self.last_elements if elem.package)
        main_package = max(packages, key=lambda p: sum(1 for e in self.last_elements if e.package == p))
        
        # Extract visible text
        visible_texts = [
            elem.text for elem in self.last_elements 
            if elem.text and len(elem.text) > 1 and elem.width > 50
        ]
        
        # Count element types
        buttons = len([e for e in self.last_elements if "Button" in e.class_name])
        textviews = len([e for e in self.last_elements if "TextView" in e.class_name])
        images = len([e for e in self.last_elements if "Image" in e.class_name])
        
        description = f"Screen Analysis:\n"
        description += f"- App: {main_package}\n"
        description += f"- Elements: {buttons} buttons, {textviews} text views, {images} images\n"
        
        if visible_texts:
            description += f"- Visible text ({len(visible_texts)} items):\n"
            for i, text in enumerate(visible_texts[:10], 1):  # Limit to 10
                description += f"  {i}. {text}\n"
            if len(visible_texts) > 10:
                description += f"  ... and {len(visible_texts) - 10} more\n"
        
        return description
    
    # -------------------------
    # Grid/List Detection
    # -------------------------
    def detect_list_items(self, min_items: int = 2) -> List[UIElement]:
        """
        Detect repeating list items (videos, posts, products, etc.).
        Returns items sorted top-to-bottom, deduplicated.
        """
        self.capture_ui_tree()
        
        # Group elements by similar heights and widths
        from collections import defaultdict
        size_groups = defaultdict(list)
        
        for elem in self.last_elements:
            # Skip tiny or full-screen elements
            if elem.width < 100 or elem.height < 100:
                continue
            if elem.width > 900 or elem.height > 1500:
                continue
            
            # Group by approximate size (rounded to nearest 50px)
            size_key = (
                round(elem.width / 50) * 50,
                round(elem.height / 50) * 50
            )
            size_groups[size_key].append(elem)
        
        # Find largest group (likely the repeating items)
        if not size_groups:
            return []
        
        largest_group = max(size_groups.values(), key=len)
        
        if len(largest_group) < min_items:
            return []
        
        # Sort by position (top to bottom, left to right)
        largest_group.sort(key=lambda e: (e.bounds[1], e.bounds[0]))
        
        # DEDUP: Remove overlapping/nested elements with same or very similar bounds
        # Nested views (parent + child) share the same bounds — keep only one per position
        deduped = []
        for elem in largest_group:
            is_duplicate = False
            for existing in deduped:
                if self._bounds_overlap(elem.bounds, existing.bounds):
                    is_duplicate = True
                    break
            if not is_duplicate:
                deduped.append(elem)
        
        return deduped
    
    @staticmethod
    def _bounds_overlap(a, b, threshold: int = 30) -> bool:
        """
        Check if two bounds overlap significantly.
        Catches nested elements (same bounds) and near-duplicates.
        
        Args:
            a, b: (left, top, right, bottom) tuples
            threshold: pixel tolerance for 'same position'
        """
        # Check if centers are very close
        cx_a, cy_a = (a[0] + a[2]) // 2, (a[1] + a[3]) // 2
        cx_b, cy_b = (b[0] + b[2]) // 2, (b[1] + b[3]) // 2
        
        if abs(cx_a - cx_b) < threshold and abs(cy_a - cy_b) < threshold:
            return True
        
        # Check if one contains the other (nested)
        if (a[0] >= b[0] - threshold and a[1] >= b[1] - threshold and
            a[2] <= b[2] + threshold and a[3] <= b[3] + threshold):
            return True
        if (b[0] >= a[0] - threshold and b[1] >= a[1] - threshold and
            b[2] <= a[2] + threshold and b[3] <= a[3] + threshold):
            return True
        
        return False
