# =========================
# FILE: agent/screen_controller.py
# =========================
"""
Unified screen controller that orchestrates:
- UI Automator (fast path)
- OCR (fallback for text)
- Ollama Vision (complex queries)
"""

import time
import os
import tempfile
from typing import Optional, Tuple, List
from agent.adb import AdbClient
from agent.device import DeviceController
from agent.ui_analyzer import UIAnalyzer, UIElement
from agent.ocr_engine import OCREngine, OCRMatch
from agent.ollama_vision import OllamaVision, VisionResult
from agent.query_router import QueryRouter, QueryIntent


class ScreenController:
    """
    Unified interface for screen analysis and interaction.
    Routes queries to the best detection method.
    """
    
    def __init__(self, adb: AdbClient, device: DeviceController) -> None:
        self.adb = adb
        self.device = device
        
        # Initialize all detection methods
        self.ui_analyzer = UIAnalyzer(adb)
        self.ocr = OCREngine()
        self.vision = OllamaVision(model="llava-phi3")
        self.router = QueryRouter()
        
        # Screenshot management (cross-platform path)
        # Windows: C:\Users\Name\AppData\Local\Temp\screenshot.png
        # Linux/Mac: /tmp/screenshot.png
        self.screenshot_path = os.path.join(tempfile.gettempdir(), "screenshot.png")
        self.last_screenshot_time = 0
        self.screenshot_cache_duration = 2  # seconds
        
        # Set screen size for vision model
        try:
            w, h = device.screen_size()
            self.vision.set_screen_size(w, h)
        except Exception:
            pass
    
    # -------------------------
    # Screenshot Management
    # -------------------------
    def capture_screenshot(self, force: bool = False) -> str:
        """
        Capture screenshot from device.
        Cached for 2 seconds unless force=True.
        
        Returns:
            Path to screenshot file
        """
        now = time.time()
        
        # Use cache if recent
        if not force and (now - self.last_screenshot_time) < self.screenshot_cache_duration:
            if os.path.exists(self.screenshot_path):
                return self.screenshot_path
        
        try:
            # Capture screenshot on device
            self.adb.run(["shell", "screencap", "-p", "/sdcard/screenshot.png"])
            
            # Pull to local
            self.adb.run(["pull", "/sdcard/screenshot.png", self.screenshot_path])
            
            self.last_screenshot_time = now
            return self.screenshot_path
            
        except Exception as e:
            print(f"âš ï¸ Screenshot failed: {e}")
            return ""
    
    # -------------------------
    # Unified Query Interface
    # -------------------------
    def execute_query(self, query: str) -> bool:
        """
        Parse and execute a screen-based query.
        
        Args:
            query: Natural language query (e.g., "click Subscribe", "first video")
        
        Returns:
            True if successful, False otherwise
        """
        # Parse query
        intent = self.router.parse_query(query)
        
        print(f"ðŸ“‹ Query type: {intent.type}")
        print(f"ðŸŽ¯ Target: {intent.target}")
        print(f"âš™ï¸ Action: {intent.action}")
        
        # Route to appropriate handler
        if intent.type == "DIRECT":
            return self._execute_direct(intent)
        
        elif intent.type == "INFO":
            return self._execute_info(intent)
        
        elif intent.type == "SCROLL_FIND":
            return self._execute_scroll_find(intent)
        
        elif intent.type == "POSITION":
            return self._execute_position(intent)
        
        elif intent.type == "VISUAL":
            return self._execute_visual(intent)
        
        elif intent.type == "TEXT_SEARCH":
            return self._execute_text_search(intent)
        
        else:
            print(f"âš ï¸ Unknown query type: {intent.type}")
            return False
    
    # -------------------------
    # Execution Handlers
    # -------------------------
    def _execute_direct(self, intent: QueryIntent) -> bool:
        """Handle direct coordinate taps"""
        # Extract coordinates from target (already validated by router)
        import re
        match = re.search(r'(\d+)\s+(\d+)', intent.target)
        if match:
            x, y = int(match.group(1)), int(match.group(2))
            self.device.tap(x, y)
            print(f"âœ… Tapped at ({x}, {y})")
            return True
        return False
    
    def _execute_info(self, intent: QueryIntent) -> bool:
        """Handle informational queries"""
        if intent.require_vision:
            # Use vision for comprehensive description
            screenshot = self.capture_screenshot()
            result = self.vision.describe_screen(screenshot, detailed=True)
            print(f"\nðŸ“± Screen Analysis:\n{result.description}\n")
        else:
            # Use UI tree + OCR for faster response
            self.ui_analyzer.capture_ui_tree()
            ui_desc = self.ui_analyzer.describe_screen()
            
            screenshot = self.capture_screenshot()
            ocr_desc = self.ocr.describe_screen(screenshot)
            
            print(f"\nðŸ“± Screen Analysis:\n{ui_desc}\n\n{ocr_desc}\n")
        
        return True
    
    def _execute_scroll_find(self, intent: QueryIntent) -> bool:
        """Handle scroll-and-find queries"""
        max_scrolls = 10
        scroll_count = 0
        
        print(f"ðŸ” Scrolling to find: {intent.target}")
        
        while scroll_count < max_scrolls:
            # Try to find element
            if intent.require_vision:
                screenshot = self.capture_screenshot(force=True)
                result = self.vision.find_element(screenshot, intent.target)
                
                if result.coordinates and result.confidence > 0.6:
                    x, y = result.coordinates
                    self.device.tap(x, y)
                    print(f"âœ… Found and tapped: {intent.target}")
                    return True
            else:
                # Use UI tree search
                elements = self.ui_analyzer.search(intent.target)
                
                if elements:
                    x, y = elements[0].center
                    self.device.tap(x, y)
                    print(f"âœ… Found and tapped: {intent.target}")
                    return True
            
            # Not found, scroll down
            print(f"   Scroll {scroll_count + 1}/{max_scrolls}...")
            self.device.scroll_once("DOWN")
            scroll_count += 1
            time.sleep(0.5)
        
        print(f"âŒ Could not find '{intent.target}' after {max_scrolls} scrolls")
        return False
    
    def _execute_position(self, intent: QueryIntent) -> bool:
        """Handle position-based queries (first, second, etc.)"""
        # Method recommendation
        method = self.router.recommend_method(intent)
        
        if method in ["ui", "hybrid"]:
            # Try UI Automator first
            items = self._find_items_ui(intent.target)
            
            if items and intent.position:
                # Handle negative positions (e.g., bottom = -1)
                if intent.position > 0:
                    idx = intent.position - 1
                else:
                    idx = intent.position
                
                if 0 <= idx < len(items) or idx < 0:
                    x, y = items[idx].center
                    self.device.tap(x, y)
                    print(f"âœ… Tapped {intent.position} {intent.target}")
                    return True
        
        # Fallback to vision
        if method in ["vision", "hybrid"]:
            screenshot = self.capture_screenshot()
            result = self.vision.find_nth_item(screenshot, intent.target, intent.position or 1)
            
            if result.coordinates and result.confidence > 0.6:
                x, y = result.coordinates
                self.device.tap(x, y)
                print(f"âœ… Tapped {intent.position} {intent.target}")
                return True
        
        print(f"âŒ Could not find {intent.position} {intent.target}")
        return False
    
    def _execute_visual(self, intent: QueryIntent) -> bool:
        """Handle visual queries (red button, car image, etc.)"""
        screenshot = self.capture_screenshot()
        
        result = self.vision.find_element(screenshot, intent.visual_desc or intent.target)
        
        if result.coordinates and result.confidence > 0.5:
            x, y = result.coordinates
            self.device.tap(x, y)
            print(f"âœ… Tapped: {result.description}")
            return True
        
        print(f"âŒ Could not find: {intent.target}")
        print(f"   Vision response: {result.description}")
        return False
    
    def _execute_text_search(self, intent: QueryIntent) -> bool:
        """Handle text-based search queries"""
        method = self.router.recommend_method(intent)
        
        # Try UI Automator first
        if method in ["ui", "hybrid"]:
            elements = self.ui_analyzer.search(intent.target)
            
            # Filter by region if specified
            if intent.region and elements:
                # Get screen bounds
                max_x = max(e.bounds[2] for e in elements)
                max_y = max(e.bounds[3] for e in elements)
                
                elements = [e for e in elements 
                           if self._in_region(e.bounds, intent.region, max_x, max_y)]
            
            if elements:
                x, y = elements[0].center
                self.device.tap(x, y)
                print(f"âœ… Tapped: {elements[0].text or elements[0].class_name}")
                return True
        
        # Fallback to OCR
        if method in ["ocr", "hybrid"] and self.ocr.available:
            screenshot = self.capture_screenshot()
            
            if intent.region:
                matches = self.ocr.find_in_region(screenshot, intent.region, intent.target)
            else:
                matches = self.ocr.find_text(screenshot, intent.target)
            
            if matches:
                x, y = matches[0].center
                self.device.tap(x, y)
                print(f"âœ… Tapped: {matches[0].text}")
                return True
        
        # Final fallback to vision
        if method in ["vision", "hybrid"] and self.vision.available:
            screenshot = self.capture_screenshot()
            result = self.vision.find_element(screenshot, intent.target)
            
            if result.coordinates and result.confidence > 0.5:
                x, y = result.coordinates
                self.device.tap(x, y)
                print(f"âœ… Tapped: {result.description}")
                return True
        
        print(f"âŒ Could not find: {intent.target}")
        return False
    
    # -------------------------
    # Helper Methods
    # -------------------------
    def _find_items_ui(self, item_type: str) -> List[UIElement]:
        """Find items using UI Automator with smart class detection"""
        self.ui_analyzer.capture_ui_tree()
        
        # Map common item types to class names
        class_mappings = {
            "video": ["Video", "Item", "Card"],
            "button": ["Button"],
            "item": ["Item", "Card", "View"],
            "post": ["Post", "Item", "Card"],
            "result": ["Result", "Item"],
            "option": ["Option", "Item"],
            "link": ["Link", "TextView"],
        }
        
        classes = class_mappings.get(item_type, ["Item", "View"])
        
        # Try each class
        for class_name in classes:
            items = self.ui_analyzer.find_by_class(class_name)
            if items:
                return items
        
        # Fallback: detect grid items
        return self.ui_analyzer.detect_list_items()
    
    def _in_region(
        self, 
        bounds: Tuple[int, int, int, int], 
        region: str, 
        max_x: int, 
        max_y: int
    ) -> bool:
        """Check if bounds are in specified region"""
        left, top, right, bottom = bounds
        
        if region == "top":
            return top < max_y * 0.25
        elif region == "bottom":
            return top > max_y * 0.75
        elif region == "left":
            return left < max_x * 0.25
        elif region == "right":
            return left > max_x * 0.75
        elif region in ["center", "middle"]:
            return (max_x * 0.25 < left < max_x * 0.75 and
                   max_y * 0.25 < top < max_y * 0.75)
        
        return True
    
    # -------------------------
    # Direct Access Methods
    # -------------------------
    def ask(self, question: str) -> str:
        """
        Ask a question about the screen.
        
        Returns:
            Answer as string
        """
        screenshot = self.capture_screenshot()
        result = self.vision.answer_question(screenshot, question)
        return result.description
    
    def find_and_tap(self, description: str) -> bool:
        """
        Find element by description and tap it.
        
        Returns:
            True if successful
        """
        return self.execute_query(f"tap {description}")
    
    def list_visible_text(self) -> List[str]:
        """
        Get all visible text elements.
        
        Returns:
            List of text strings
        """
        self.ui_analyzer.capture_ui_tree()
        
        texts = []
        for elem in self.ui_analyzer.last_elements:
            if elem.text and len(elem.text) > 1:
                texts.append(elem.text)
        
        return texts
