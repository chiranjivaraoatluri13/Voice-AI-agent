# =========================
# FILE: agent/ui_analyzer.py
# =========================
"""
UI Automator wrapper for fast element detection.
Parses XML hierarchy and finds elements by text, ID, class, etc.
"""

import xml.etree.ElementTree as ET
from typing import List, Optional, Tuple
from dataclasses import dataclass
from agent.adb import AdbClient


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
    
    def __repr__(self) -> str:
        return (f"UIElement(text='{self.text}', id='{self.resource_id}', "
                f"class='{self.class_name}', bounds={self.bounds})")


class UIAnalyzer:
    """
    Fast UI tree analysis using Android's UI Automator.
    """
    
    def __init__(self, adb: AdbClient) -> None:
        self.adb = adb
        self.last_tree: Optional[ET.Element] = None
        self.last_elements: List[UIElement] = []
        self._last_capture_time: float = 0
        self._cache_ttl: float = 3.0  # seconds before auto-refresh
    
    # -------------------------
    # UI Hierarchy Capture
    # -------------------------
    def capture_ui_tree(self, force_refresh: bool = False) -> None:
        """
        Capture current UI hierarchy from device.
        Auto-refreshes if cache is older than 3 seconds.
        """
        import time
        now = time.time()
        is_stale = (now - self._last_capture_time) > self._cache_ttl
        
        if not force_refresh and not is_stale and self.last_tree is not None:
            return
        
        try:
            # Dump UI hierarchy to device
            self.adb.run(["shell", "uiautomator", "dump", "/sdcard/ui_dump.xml"])
            
            # Pull to local
            xml_content = self.adb.run(["shell", "cat", "/sdcard/ui_dump.xml"])
            
            # Parse XML
            self.last_tree = ET.fromstring(xml_content)
            
            # Parse all elements
            self.last_elements = self._parse_tree(self.last_tree)
            self._last_capture_time = now
            
        except Exception as e:
            print(f"âš ï¸ UI tree capture failed: {e}")
            self.last_tree = None
            self.last_elements = []
    
    def _parse_tree(self, root: ET.Element) -> List[UIElement]:
        """Recursively parse XML tree into UIElement objects"""
        elements = []
        
        def parse_node(node: ET.Element):
            # Parse bounds: "[x1,y1][x2,y2]" â†’ (x1, y1, x2, y2)
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
            )
            
            elements.append(element)
            
            # Recurse children
            for child in node:
                parse_node(child)
        
        parse_node(root)
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
        Auto-refreshes UI tree if stale (>3 sec old).
        Returns ranked results, preferring elements with actual text.
        """
        self.capture_ui_tree()  # TTL-based auto-refresh
        
        query_lower = query.lower()
        scored_results = []
        
        for elem in self.last_elements:
            score = 0
            
            # Exact text match (highest priority)
            if elem.text and elem.text.lower() == query_lower:
                score += 100
            
            # Text contains query
            elif elem.text and query_lower in elem.text.lower():
                score += 50
            
            # Content description match
            if elem.content_desc and query_lower in elem.content_desc.lower():
                score += 30
            
            # Resource ID match
            if elem.resource_id and query_lower in elem.resource_id.lower():
                score += 20
            
            # Boost clickable elements
            if elem.clickable:
                score += 10
            
            # PENALIZE containers with no text (LinearLayout, FrameLayout, etc.)
            # These often match via clickable boost alone and cause wrong taps
            if score > 0 and not elem.text and not elem.content_desc:
                container_classes = ["Layout", "ViewGroup", "RecyclerView", "ScrollView"]
                if any(c in elem.class_name for c in container_classes):
                    score -= 15  # Push below text-bearing elements
            
            if score > 0:
                scored_results.append((score, elem))
        
        # Sort by score descending
        scored_results.sort(key=lambda x: x[0], reverse=True)
        
        return [elem for score, elem in scored_results]
    
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
        Detect feed/list items (videos, posts, pins, etc.).
        
        Strategy order:
        1. Find RecyclerView children (most reliable)
        2. Find clickable elements with content (text/desc) in scroll area
        3. Size-grouping fallback
        """
        self.capture_ui_tree()
        if not self.last_elements:
            return []
        
        # Get screen bounds
        max_w = max((e.bounds[2] for e in self.last_elements), default=1080)
        max_h = max((e.bounds[3] for e in self.last_elements), default=2400)
        
        # Strategy 1: Find items inside RecyclerView/ListView
        items = self._find_recycler_children(max_w, max_h)
        if len(items) >= min_items:
            return items
        
        # Strategy 2: Clickable content elements in the main scroll area
        items = self._find_clickable_content(max_w, max_h)
        if len(items) >= min_items:
            return items
        
        # Strategy 3: Size-grouping fallback
        items = self._find_by_size_grouping(max_w, max_h, min_items)
        return items
    
    def _find_recycler_children(self, max_w: int, max_h: int) -> List[UIElement]:
        """Find children of RecyclerView/ListView — these ARE the list items."""
        # First find the scrollable/recycler container
        recycler = None
        recycler_area = 0
        
        for elem in self.last_elements:
            cls = elem.class_name.lower()
            if any(rv in cls for rv in ["recyclerview", "listview", "gridview"]):
                area = elem.width * elem.height
                if area > recycler_area:
                    recycler = elem
                    recycler_area = area
        
        if not recycler:
            # Also try scrollable elements
            for elem in self.last_elements:
                if elem.scrollable and elem.width > max_w * 0.5 and elem.height > max_h * 0.3:
                    area = elem.width * elem.height
                    if area > recycler_area:
                        recycler = elem
                        recycler_area = area
        
        if not recycler:
            return []
        
        # Find elements that are direct content inside this recycler
        # They should: be inside recycler bounds, be substantial size, be at the top level
        rl, rt, rr, rb = recycler.bounds
        items = []
        
        for elem in self.last_elements:
            if elem is recycler:
                continue
            el, et, er, eb = elem.bounds
            
            # Must be inside recycler
            if el < rl or et < rt or er > rr + 5 or eb > rb + 5:
                continue
            
            w, h = elem.width, elem.height
            
            # Must be substantial (not tiny icons or text fragments)
            if w < max_w * 0.3 or h < 80:
                continue
            
            # Skip if it's basically the full recycler (it IS the recycler)
            if w >= (rr - rl) * 0.95 and h >= (rb - rt) * 0.8:
                continue
            
            # Must be clickable OR have content
            if elem.clickable or elem.text or elem.content_desc:
                items.append(elem)
        
        if not items:
            return []
        
        # Deduplicate: if elements overlap vertically, keep the larger one
        items.sort(key=lambda e: e.bounds[1])
        deduped = []
        for item in items:
            if deduped:
                last = deduped[-1]
                # Check vertical overlap
                overlap = min(last.bounds[3], item.bounds[3]) - max(last.bounds[1], item.bounds[1])
                if overlap > min(last.height, item.height) * 0.5:
                    # Keep the larger/more clickable one
                    if item.height > last.height or (item.clickable and not last.clickable):
                        deduped[-1] = item
                    continue
            deduped.append(item)
        
        return deduped
    
    def _find_clickable_content(self, max_w: int, max_h: int) -> List[UIElement]:
        """
        Find clickable elements with content in the main content area.
        Filters out toolbar, nav bar, and tiny elements.
        """
        # Content area: skip top 10% (toolbar) and bottom 10% (nav)
        content_top = max_h * 0.10
        content_bottom = max_h * 0.90
        
        items = []
        for elem in self.last_elements:
            # Must be clickable
            if not elem.clickable:
                continue
            
            # Must be in content area
            if elem.bounds[1] < content_top or elem.bounds[3] > content_bottom:
                continue
            
            # Must have real size (not tiny icons)
            if elem.width < max_w * 0.25 or elem.height < 80:
                continue
            
            # Must have content OR be a substantial container
            has_content = bool(elem.text or elem.content_desc)
            is_substantial = elem.height > 150 and elem.width > max_w * 0.4
            
            if has_content or is_substantial:
                items.append(elem)
        
        if not items:
            return []
        
        # Sort top to bottom
        items.sort(key=lambda e: e.bounds[1])
        
        # Deduplicate overlapping items (keep the best one)
        deduped = []
        for item in items:
            if deduped:
                last = deduped[-1]
                overlap = min(last.bounds[3], item.bounds[3]) - max(last.bounds[1], item.bounds[1])
                if overlap > min(last.height, item.height) * 0.3:
                    # Keep the one with more content or larger area
                    last_score = (1 if last.text else 0) + (1 if last.content_desc else 0) + last.height
                    item_score = (1 if item.text else 0) + (1 if item.content_desc else 0) + item.height
                    if item_score > last_score:
                        deduped[-1] = item
                    continue
            deduped.append(item)
        
        return deduped
    
    def _find_by_size_grouping(self, max_w: int, max_h: int, min_items: int) -> List[UIElement]:
        """Original size-grouping approach as final fallback."""
        from collections import defaultdict
        size_groups = defaultdict(list)
        
        for elem in self.last_elements:
            w, h = elem.width, elem.height
            if w < 80 or h < 80:
                continue
            if w >= max_w * 0.98 and h >= max_h * 0.8:
                continue
            if h > max_h * 0.6:
                continue
            if not (elem.clickable or elem.text or elem.content_desc):
                continue
            size_key = (round(w / 50) * 50, round(h / 50) * 50)
            size_groups[size_key].append(elem)
        
        if not size_groups:
            return []
        
        candidates = [g for g in size_groups.values() if len(g) >= min_items]
        if not candidates:
            return []
        
        largest = max(candidates, key=len)
        largest.sort(key=lambda e: (e.bounds[1], e.bounds[0]))
        return largest
