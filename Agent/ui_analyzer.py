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
    
    # -------------------------
    # UI Hierarchy Capture
    # -------------------------
    def capture_ui_tree(self, force_refresh: bool = False) -> None:
        """
        Capture current UI hierarchy from device.
        Cached by default unless force_refresh=True.
        """
        if not force_refresh and self.last_tree is not None:
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
        ALWAYS refreshes UI tree (screen may have changed after scroll).
        Returns ranked results, preferring elements with actual text.
        """
        self.capture_ui_tree(force_refresh=True)
        
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
        Detect repeating list items (videos, posts, products, etc.).
        Returns items sorted top-to-bottom.
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
        
        return largest_group
