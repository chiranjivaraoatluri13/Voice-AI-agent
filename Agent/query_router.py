# =========================
# FILE: agent/query_router.py
# =========================
"""
Intelligent query routing to choose the best method:
- UI Automator (fast, 95% accuracy for accessible elements)
- OCR (medium, 85% accuracy for text)
- Ollama Vision (slow, 90% accuracy for complex queries)
"""

import re
from typing import Optional, Literal
from dataclasses import dataclass

QueryType = Literal["DIRECT", "TEXT_SEARCH", "POSITION", "VISUAL", "INFO", "SCROLL_FIND"]


@dataclass
class QueryIntent:
    """Parsed query intent"""
    
    type: QueryType
    target: str  # What to find/interact with
    action: str  # What to do (tap, scroll, describe)
    position: Optional[int] = None  # For "first", "second", etc.
    region: Optional[str] = None  # For "top", "bottom", etc.
    visual_desc: Optional[str] = None  # For "red button", "car image"
    
    # Method recommendations
    prefer_ui_automator: bool = True
    require_vision: bool = False
    allow_ocr: bool = True


class QueryRouter:
    """
    Analyzes user queries and routes to appropriate detection method.
    """
    
    # Keywords that indicate different query types
    POSITION_KEYWORDS = {
        "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
        "1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5,
        "top": 1, "bottom": -1,
    }
    
    REGION_KEYWORDS = ["top", "bottom", "left", "right", "center", "middle"]
    
    VISUAL_KEYWORDS = [
        "red", "blue", "green", "yellow", "orange", "purple", "pink", "black", "white",
        "color", "colored", "icon", "image", "picture", "photo", "thumbnail",
        "logo", "avatar", "profile", "car", "cat", "dog", "person", "face"
    ]
    
    INFO_KEYWORDS = [
        "what", "describe", "tell me", "show me", "list", "how many",
        "see", "visible", "on screen", "display"
    ]
    
    SCROLL_KEYWORDS = ["scroll until", "find by scrolling", "search for"]
    
    def parse_query(self, query: str) -> QueryIntent:
        """
        Parse user query and determine routing strategy.
        
        Returns:
            QueryIntent with routing recommendations
        """
        q = query.strip().lower()
        
        # 1. Check for direct coordinates
        if self._is_direct_coordinate(q):
            return QueryIntent(
                type="DIRECT",
                target=query,
                action="tap",
                prefer_ui_automator=False,
                require_vision=False
            )
        
        # 2. Check for informational queries
        if self._is_info_query(q):
            return self._parse_info_query(query)
        
        # 3. Check for scroll-and-find queries
        if self._is_scroll_find_query(q):
            return self._parse_scroll_find_query(query)
        
        # 4. Check for position-based queries
        position = self._extract_position(q)
        if position:
            return self._parse_position_query(query, position)
        
        # 5. Check for visual queries
        if self._has_visual_keywords(q):
            return self._parse_visual_query(query)
        
        # 6. Default: text-based search
        return self._parse_text_query(query)
    
    # -------------------------
    # Query Type Checkers
    # -------------------------
    def _is_direct_coordinate(self, query: str) -> bool:
        """Check if query is direct tap coordinates"""
        # Pattern: "tap 100 200" or "click 540 1200"
        return bool(re.match(r'(tap|click)\s+\d+\s+\d+', query))
    
    def _is_info_query(self, query: str) -> bool:
        """Check if query is asking for information"""
        return any(keyword in query for keyword in self.INFO_KEYWORDS)
    
    def _is_scroll_find_query(self, query: str) -> bool:
        """Check if query requires scrolling to find element"""
        return any(keyword in query for keyword in self.SCROLL_KEYWORDS)
    
    def _has_visual_keywords(self, query: str) -> bool:
        """Check if query mentions visual characteristics"""
        return any(keyword in query for keyword in self.VISUAL_KEYWORDS)
    
    def _extract_position(self, query: str) -> Optional[int]:
        """Extract position number from query"""
        for keyword, position in self.POSITION_KEYWORDS.items():
            if keyword in query:
                return position
        return None
    
    def _extract_region(self, query: str) -> Optional[str]:
        """Extract screen region from query"""
        for region in self.REGION_KEYWORDS:
            if region in query:
                return region
        return None
    
    # -------------------------
    # Query Parsers
    # -------------------------
    def _parse_info_query(self, query: str) -> QueryIntent:
        """Parse informational queries like 'what do you see?'"""
        q = query.lower()
        
        # Determine what information is requested
        if "video" in q:
            target = "videos"
        elif "button" in q:
            target = "buttons"
        elif "text" in q:
            target = "text"
        else:
            target = "all"
        
        return QueryIntent(
            type="INFO",
            target=target,
            action="describe",
            prefer_ui_automator=True,
            require_vision="what" in q or "describe" in q,  # Use vision for "what do you see?"
            allow_ocr=True
        )
    
    def _parse_scroll_find_query(self, query: str) -> QueryIntent:
        """Parse scroll-and-find queries"""
        # Extract what to find
        # "scroll until you find X" → target = X
        match = re.search(r'(scroll until|find by scrolling|search for)\s+(.+)', query.lower())
        
        if match:
            target = match.group(2).strip()
        else:
            target = query
        
        # Check if visual search needed
        require_vision = self._has_visual_keywords(query.lower())
        
        return QueryIntent(
            type="SCROLL_FIND",
            target=target,
            action="scroll_and_find",
            prefer_ui_automator=not require_vision,
            require_vision=require_vision,
            allow_ocr=True
        )
    
    def _parse_position_query(self, query: str, position: int) -> QueryIntent:
        """Parse position-based queries like 'first video', 'second button'"""
        q = query.lower()
        
        # Extract what type of element
        # Common patterns: "first video", "second button", "top item"
        element_types = ["video", "button", "item", "post", "result", "option", "link"]
        
        target = "item"  # default
        for elem_type in element_types:
            if elem_type in q:
                target = elem_type
                break
        
        return QueryIntent(
            type="POSITION",
            target=target,
            action="tap",
            position=position,
            prefer_ui_automator=True,
            require_vision=False,
            allow_ocr=True
        )
    
    def _parse_visual_query(self, query: str) -> QueryIntent:
        """Parse visual queries like 'red button', 'pin with car'"""
        q = query.lower()
        
        # Extract visual description
        # Remove action words
        visual_desc = re.sub(r'(click|tap|open|find|select)\s+', '', q)
        visual_desc = re.sub(r'(the|a|an)\s+', '', visual_desc)
        
        # Determine action
        if "open" in q:
            action = "open"
        elif "click" in q or "tap" in q or "select" in q:
            action = "tap"
        else:
            action = "find"
        
        return QueryIntent(
            type="VISUAL",
            target=visual_desc.strip(),
            action=action,
            visual_desc=visual_desc.strip(),
            prefer_ui_automator=False,
            require_vision=True,
            allow_ocr=False
        )
    
    def _parse_text_query(self, query: str) -> QueryIntent:
        """Parse simple text-based queries like 'click Subscribe'"""
        q = query.lower()
        
        # Extract action
        if "click" in q or "tap" in q:
            action = "tap"
            # Remove action word to get target
            target = re.sub(r'(click|tap)\s+(on\s+)?(the\s+)?', '', q).strip()
        elif "open" in q:
            action = "open"
            target = re.sub(r'open\s+(the\s+)?', '', q).strip()
        else:
            action = "tap"
            target = q.strip()
        
        # Check if region specified
        region = self._extract_region(q)
        
        return QueryIntent(
            type="TEXT_SEARCH",
            target=target,
            action=action,
            region=region,
            prefer_ui_automator=True,
            require_vision=False,
            allow_ocr=True
        )
    
    # -------------------------
    # Method Selection
    # -------------------------
    def recommend_method(self, intent: QueryIntent) -> Literal["ui", "ocr", "vision", "hybrid"]:
        """
        Recommend which detection method to use.
        
        Returns:
            "ui" = UI Automator only
            "ocr" = OCR only
            "vision" = Ollama Vision only
            "hybrid" = Try UI, fallback to OCR/Vision
        """
        if intent.require_vision:
            return "vision"
        
        if intent.prefer_ui_automator and intent.allow_ocr:
            return "hybrid"  # Try UI first, fallback to OCR
        
        if intent.prefer_ui_automator:
            return "ui"
        
        if intent.allow_ocr and not intent.require_vision:
            return "ocr"
        
        return "vision"  # Default fallback
    
    # -------------------------
    # Confidence Scoring
    # -------------------------
    def estimate_success_rate(self, intent: QueryIntent) -> float:
        """
        Estimate probability of successful execution.
        
        Returns:
            Float 0-1 (e.g., 0.85 = 85% confidence)
        """
        base_scores = {
            "DIRECT": 0.99,
            "TEXT_SEARCH": 0.90,
            "POSITION": 0.85,
            "VISUAL": 0.75,
            "INFO": 0.80,
            "SCROLL_FIND": 0.70,
        }
        
        score = base_scores.get(intent.type, 0.5)
        
        # Adjust based on method
        if intent.require_vision:
            score *= 0.95  # Vision slightly less reliable
        
        if intent.prefer_ui_automator:
            score *= 1.05  # UI Automator very reliable
        
        return min(score, 0.99)
