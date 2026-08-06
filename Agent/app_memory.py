# =========================
# FILE: agent/app_memory.py
# =========================
"""
App UI Component Knowledge Base.

Holds curated, hand-written rules (resource IDs + descriptors) for common app
components. These are stable identifiers, not observations of a past screen.

Deliberately NOT persisted from runtime: remembering a concrete element that
once worked meant replaying stale bounds and labels from an older screen, which
produced taps on unrelated widgets. Live resolution against the current UI tree
(ScreenInspector) is the source of truth instead.
"""

import re
from typing import Optional, Dict


def _has_word(haystack: str, needle: str) -> bool:
    """Whole-word (or whole-phrase) containment.

    Plain substring matching made "subscribe" match "59.3K subscribers", so the
    agent tapped the channel row and navigated away instead of subscribing.
    """
    if not haystack or not needle:
        return False
    return bool(re.search(rf'(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])',
                          haystack, re.I))


KNOWN_APP_COMPONENTS = {
    "youtube": {
        "search_bar": {
            "resource_ids": [
                "search_edit_text", "search_box", "menu_search",
                "search_button", "action_search",
            ],
            "descriptors": [
                "search youtube", "search", "search…", "search...",
            ],
            "exclude_keywords": ["voice", "mic", "microphone", "speech"],
        },
        "subscribe_button": {
            "resource_ids": ["subscribe_button", "subscribe"],
            "descriptors": ["subscribe", "subscribe to", "subscribe button", "subscribed"],
            # "59.3K subscribers" contains "subscribe" — it is the channel row,
            # and tapping it opens the channel instead of subscribing.
            "exclude_keywords": ["subscribers", "subscriber", "subscriptions"],
        },
        "like_button": {
            "resource_ids": ["like_button", "like"],
            "descriptors": ["like", "like this video", "unlike", "remove like"],
            "exclude_keywords": ["likes", "liked by", "dislike"],
        },
        "dislike_button": {
            "resource_ids": ["dislike_button", "dislike"],
            "descriptors": ["dislike", "dislike this video", "undislike"],
        },
        "play_pause": {
            "descriptors": ["play video", "pause video", "play", "pause"],
        },
    },
    "chrome": {
        "search_bar": {
            "resource_ids": [
                "url_bar", "search_box_text", "omnibox", "url_bar_title",
                "search_box", "location_bar",
            ],
            "descriptors": [
                "search google or type url",
                "search or type url",
                "search or type web address",
                "type url",
                "address and search bar",
                "search google",
            ],
            "exclude_keywords": ["voice", "mic", "microphone"],
        },
        "url_bar": {
            "resource_ids": ["url_bar", "search_box_text", "omnibox"],
            "descriptors": [
                "search google or type url",
                "search or type url",
                "search or type web address",
            ],
        },
    },
    "google": {
        "search_bar": {
            "resource_ids": [
                "search_box", "search_edit_frame", "open_search_view",
                "googleapp_search_box", "hint_text",
            ],
            "descriptors": [
                "search", "search google", "google search",
            ],
            "exclude_keywords": ["voice", "mic", "microphone", "lens", "camera"],
        },
    },
    "whatsapp": {
        "search_bar": {
            "resource_ids": ["menu_search", "search"],
            "descriptors": ["search...", "search"],
        },
        "message_input": {
            "resource_ids": ["entry", "message_input_text"],
            "descriptors": ["type a message", "message"],
        },
        "send_button": {
            "resource_ids": ["send", "btn_send"],
            "descriptors": ["send"],
        },
    },
    "settings": {
        "search_bar": {
            "resource_ids": ["search_action_bar", "search_src_text"],
            "descriptors": ["search settings"],
        },
    },
    "playstore": {
        "search_bar": {
            "resource_ids": [
                "search_box", "search_bar", "search_edit_frame",
                "search_src_text", "action_search", "menu_search",
            ],
            "descriptors": ["search", "search apps & games", "search google play"],
            "exclude_keywords": ["voice", "mic", "microphone", "camera", "lens"],
        },
    },
}

# Package substring → memory app key
PACKAGE_TO_APP = {
    "android.youtube": "youtube",
    "chrome": "chrome",
    "googlequicksearchbox": "google",
    "android.googlequicksearchbox": "google",
    "whatsapp": "whatsapp",
    "settings": "settings",
    "vending": "playstore",
    "finsky": "playstore",
}


class AppUIMemory:
    """Curated UI component rules. Read-only at runtime."""

    def __init__(self) -> None:
        self.memory: Dict[str, Dict] = {
            app: {role: dict(rule) for role, rule in comps.items()}
            for app, comps in KNOWN_APP_COMPONENTS.items()
        }

    def app_key_from_package(self, package: str) -> str:
        pkg = (package or "").lower()
        for needle, key in PACKAGE_TO_APP.items():
            if needle in pkg:
                return key
        # fallback: last segment
        if pkg:
            return pkg.split(".")[-1]
        return ""

    def get_app_component(self, app_name: str, component_name: str) -> Optional[Dict]:
        app_key = app_name.lower().strip()
        for k in self.memory:
            if k in app_key or app_key in k:
                return self.memory[k].get(component_name)
        return None

    QUERY_TO_COMPONENT = {
        "subscribe": "subscribe_button",
        "unsubscribe": "subscribe_button",
        "like": "like_button",
        "unlike": "like_button",
        "dislike": "dislike_button",
        "undislike": "dislike_button",
        "search": "search_bar",
        "search bar": "search_bar",
        "send": "send_button",
        "message": "message_input",
        "type a message": "message_input",
        "play": "play_pause",
        "pause": "play_pause",
        "url": "url_bar",
        "url bar": "url_bar",
        "address bar": "url_bar",
        "omnibox": "url_bar",
    }

    def resolve_search_bar_by_id(self, package: str, elements: list) -> Optional[object]:
        """
        Resolve a search / URL bar from curated resource IDs on the CURRENT tree.

        Only the app whose package is on screen is consulted, and only its
        resource-ID rules — descriptor-only guesses like "search" match nav tabs
        and labels far too easily.
        """
        if not elements:
            return None
        app_key = self.app_key_from_package(package)
        if not app_key or app_key not in self.memory:
            return None

        for role in ("search_bar", "url_bar"):
            rule = self.memory[app_key].get(role)
            if not isinstance(rule, dict):
                continue
            found = self._match_rule(rule, elements, require_resource_id=True)
            if found is not None:
                return found
        return None

    @staticmethod
    def _is_tappable(elem) -> bool:
        """Reject degenerate/off-screen elements (a (0,0) tap does nothing useful)."""
        try:
            x0, y0, x1, y1 = elem.bounds
        except Exception:
            return False
        if x1 - x0 < 8 or y1 - y0 < 8:
            return False
        cx, cy = elem.center
        return cx > 0 and cy > 0

    def _match_rule(self, rule: Dict, elements: list,
                    require_resource_id: bool = False) -> Optional[object]:
        resource_ids = [r.lower() for r in rule.get("resource_ids", [])]
        descriptors = [d.lower() for d in rule.get("descriptors", []) if len(d) > 3]
        exclude = [e.lower() for e in rule.get("exclude_keywords", [])]
        best = None
        best_score = 0
        for elem in elements:
            if not self._is_tappable(elem):
                continue
            text = (getattr(elem, "text", None) or "").lower()
            desc = (getattr(elem, "content_desc", None) or "").lower()
            rid = (getattr(elem, "resource_id", None) or "").lower()
            combined = f"{text} {desc} {rid}"
            if exclude and any(_has_word(combined, ex) for ex in exclude):
                continue
            rid_tail = rid.split("/")[-1] if rid else ""
            id_hit = bool(resource_ids) and any(r in rid or r == rid_tail for r in resource_ids)
            if require_resource_id and not id_hit:
                continue
            score = 0
            if id_hit:
                score += 40
            if descriptors and any(
                _has_word(text, d) or _has_word(desc, d) for d in descriptors
            ):
                score += 25
            if "EditText" in (getattr(elem, "class_name", "") or ""):
                score += 10
            if getattr(elem, "clickable", False):
                score += 3
            if score > best_score:
                best_score = score
                best = elem
        return best if best_score >= 25 else None

    def resolve_in_elements(self, package: str, query: str, elements: list) -> Optional[object]:
        if not elements or not query:
            return None

        q = query.lower().strip()
        pkg = (package or "").lower()
        app_key = self.app_key_from_package(pkg) if pkg else ""

        if not app_key:
            for k in self.memory:
                if k in pkg or k in q:
                    app_key = k
                    break

        component_key = self.QUERY_TO_COMPONENT.get(q)
        if not component_key:
            for alias, key in self.QUERY_TO_COMPONENT.items():
                # Only widen on whole-word aliases; `q in alias` let "s" match
                # "search" and dragged unrelated taps into component rules.
                if alias in q.split() or alias == q:
                    component_key = key
                    break
        # Direct role names
        if q.replace(" ", "_") in ("search_bar", "url_bar", "subscribe_button"):
            component_key = q.replace(" ", "_")

        # Rules are only valid for the app they were written for. Falling back to
        # another app's rules matched foreign widgets on the current screen.
        if not app_key or not component_key:
            return None
        rule = self.memory.get(app_key, {}).get(component_key)
        if not isinstance(rule, dict):
            return None
        return self._match_rule(rule, elements)


APP_MEMORY = AppUIMemory()
