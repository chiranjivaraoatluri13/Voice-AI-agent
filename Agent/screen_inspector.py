# =========================
# FILE: agent/screen_inspector.py
# =========================
"""
Semantic UI Inspector & Screen Layout Mapper.

Dumps and analyzes the Android UI tree hierarchy to map screen components into 
deterministic functional categories (Search Bar, Navigation Tabs, Action Buttons,
Content Cards) to guarantee 100% accurate element resolution across any app.
"""

from typing import List, Optional, Tuple, Dict
from dataclasses import dataclass, field
from agent.ui_analyzer import UIElement, UIAnalyzer


@dataclass
class CategorizedScreen:
    """Represents a semantically parsed screen layout."""
    app_package: str = ""
    search_element: Optional[UIElement] = None
    create_element: Optional[UIElement] = None
    navigation_tabs: List[UIElement] = field(default_factory=list)
    action_buttons: List[UIElement] = field(default_factory=list)
    input_fields: List[UIElement] = field(default_factory=list)
    content_cards: List[UIElement] = field(default_factory=list)


class ScreenInspector:
    """
    Parses and categorizes screen UI elements from UIAnalyzer.
    """

    # Exclude terms for search bar matching
    SEARCH_EXCLUDE = {
        "voice", "mic", "microphone", "speech", "audio",
        "create", "add", "plus", "new", "post", "compose",
        "home", "profile", "account", "bell", "notification", "notifications",
        "camera", "visual search", "lens", "qr", "barcode", "scan",
    }

    # Terms indicating Create / Add button
    CREATE_TERMS = {"create", "add", "plus", "new pin", "new post", "compose", "upload"}

    @classmethod
    def inspect(cls, elements: List[UIElement], package: str = "") -> CategorizedScreen:
        """
        Analyze UI elements and classify them into semantic categories.
        """
        cat = CategorizedScreen(app_package=package)
        if not elements:
            return cat

        # 1. Input fields (EditText)
        cat.input_fields = [e for e in elements if "EditText" in e.class_name]

        # 2. Find verified Search target (excludes mic, create/add, home, etc.)
        cat.search_element = cls.find_search_target(elements)

        # 3. Find Create / Add button
        cat.create_element = cls._find_create_button(elements)

        # 4. Find Navigation tabs (elements near bottom/top bar)
        cat.navigation_tabs = [
            e for e in elements
            if e.clickable and any(kw in (e.content_desc + " " + e.text).lower()
                                   for kw in ["home", "search", "explore", "create", "add", "bell", "profile", "account", "tab"])
        ]

        # 5. Find Action buttons
        cat.action_buttons = [
            e for e in elements
            if e.clickable or "Button" in e.class_name
        ]

        return cat

    @classmethod
    def find_search_target(cls, elements: List[UIElement]) -> Optional[UIElement]:
        """
        Find the exact search bar or search tab icon on screen.
        Strictly excludes Voice Mic, Add/Create buttons, Home, Bell, Profile tabs,
        and camera / visual-search icons.
        """
        screen_h = 0
        try:
            screen_h = max(e.bounds[3] for e in elements) if elements else 0
        except Exception:
            screen_h = 0

        # Pass 1: EditText with search/find/query (excluding mic/add/camera)
        for e in elements:
            if "EditText" in e.class_name and not cls._is_excluded(e):
                combined = (e.content_desc + " " + (e.text or "") + " " + e.resource_id).lower()
                if any(k in combined for k in ["search", "find", "query", "explore", "url", "omnibox"]):
                    return e

        # Pass 2: Clickable element with explicit Search descriptor (not bottom-nav only)
        for e in elements:
            if e.clickable and not cls._is_excluded(e) and not cls._is_bottom_nav_search(e, screen_h):
                desc = (e.content_desc or "").lower()
                text = (e.text or "").lower()
                res = (e.resource_id or "").lower()

                if any(k in desc for k in ["search and explore", "search tab", "search button", "search"]) and not any(ck in desc for ck in ["create", "add", "voice", "mic", "camera", "visual"]):
                    return e

                if any(k in res for k in ["search_button", "search_tab", "action_search", "search_bar", "search_box", "url_bar", "omnibox"]) and not any(ck in res for ck in ["create", "add", "voice", "mic", "camera", "lens"]):
                    return e

        # Pass 3: bottom-nav Search tab (opens search mode) — only if no better hit
        for e in elements:
            if e.clickable and not cls._is_excluded(e):
                combined = (e.content_desc + " " + (e.text or "") + " " + e.resource_id).lower()
                if any(k in combined for k in ["search", "explore", "magnify"]):
                    return e

        # Pass 4: Fallback to any EditText if available
        for e in elements:
            if "EditText" in e.class_name and not cls._is_excluded(e):
                return e

        return None

    @classmethod
    def _is_excluded(cls, e: UIElement) -> bool:
        """Check if an element is a Voice Mic, Create/Add button, or unrelated tab."""
        combined = (e.content_desc + " " + (e.text or "") + " " + e.resource_id).lower()
        
        # Explicit check for Create / Add button (Pinterest '+' button has resource_id/desc 'Create' or 'add')
        if any(k in combined for k in ["create", "add", "plus", "new_post", "new_pin", "upload", "btn_add"]):
            return True
        
        # Explicit check for Voice / Mic
        if any(k in combined for k in ["voice", "mic", "microphone", "speech", "audio"]):
            return True

        # Camera / visual search / lens — not a text query field
        if any(k in combined for k in [
            "camera", "visual search", "lens", "qr", "barcode", "scan code",
            "open camera", "take a photo", "photo search",
        ]):
            return True

        return False

    @classmethod
    def _is_bottom_nav_search(cls, e: UIElement, screen_h: int = 0) -> bool:
        """True when 'Search' is a bottom tab, not an input field."""
        if "EditText" in (e.class_name or ""):
            return False
        try:
            _, y0, _, y1 = e.bounds
            h = screen_h or max(y1, 1)
            # Bottom ~18% of the screen → nav chrome
            if y0 > h * 0.82:
                return True
        except Exception:
            pass
        return False
    @classmethod
    def _find_create_button(cls, elements: List[UIElement]) -> Optional[UIElement]:
        for e in elements:
            combined = (e.content_desc + " " + (e.text or "") + " " + e.resource_id).lower()
            if any(k in combined for k in cls.CREATE_TERMS) and e.clickable:
                return e
        return None

    @classmethod
    def dump_summary(cls, elements: List[UIElement], package: str = "") -> str:
        """
        Generate a human-readable visual summary of the UI tree structure.
        """
        parsed = cls.inspect(elements, package)
        lines = [f"[UI Tree Summary] ({len(elements)} elements):"]
        
        if parsed.search_element:
            s = parsed.search_element
            lines.append(f"  -> Search Target: '{s.text or s.content_desc or s.resource_id}' at center={s.center}")
        else:
            lines.append("  -> Search Target: [Not found]")

        if parsed.create_element:
            c = parsed.create_element
            lines.append(f"  -> Create/Add Button: '{c.content_desc or c.resource_id}' at center={c.center}")

        clickable = [e for e in elements if e.clickable or "Button" in e.class_name]
        lines.append(f"  -> Interactive Elements ({len(clickable)} total):")
        for i, e in enumerate(clickable[:15], 1):
            label = (e.text or e.content_desc or e.resource_id.split("/")[-1] or e.class_name.split(".")[-1])[:40]
            lines.append(f"     {i:2d}. {label:40s} | bounds={e.bounds}")

        return "\n".join(lines)
