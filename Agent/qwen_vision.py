# =========================
# FILE: agent/qwen_vision.py
# =========================
"""
Qwen-VL integration for on-device vision understanding.
Handles icon detection, UI element location, and visual reasoning.
"""

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from PIL import Image
import json
from typing import Optional, Tuple, Dict, List
from dataclasses import dataclass


@dataclass
class VisionResult:
    """Result from Qwen-VL vision analysis"""
    description: str
    coordinates: Optional[Tuple[int, int]] = None
    confidence: float = 0.0
    elements: List[Dict] = None
    
    def __post_init__(self):
        if self.elements is None:
            self.elements = []


class QwenVisionEngine:
    """
    On-device vision understanding using Qwen-VL.
    Fast, accurate, completely offline.
    """
    
    def __init__(self, model_name: str = "Qwen/Qwen-VL-Chat"):
        self.model_name = model_name
        self.model = None
        self.tokenizer = None
        self.available = False
        self.screen_width = 1080
        self.screen_height = 2400
        
        self._load_model()
    
    def _load_model(self):
        """Load Qwen-VL model"""
        try:
            print(f"📥 Loading Qwen-VL model...")
            
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.model_name,
                trust_remote_code=True
            )
            
            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_name,
                device_map="auto",
                trust_remote_code=True,
                torch_dtype=torch.float16  # FP16 for speed
            ).eval()
            
            self.available = True
            print(f"✅ Qwen-VL ready!")
            
        except Exception as e:
            print(f"⚠️ Could not load Qwen-VL: {e}")
            print("   Run: pip install transformers accelerate tiktoken")
            self.available = False
    
    def set_screen_size(self, width: int, height: int):
        """Update screen dimensions"""
        self.screen_width = width
        self.screen_height = height
    
    # ===========================
    # Core Vision Methods
    # ===========================
    
    def analyze_screen(self, image_path: str, query: str) -> VisionResult:
        """
        Analyze screen with natural language query.
        
        Args:
            image_path: Path to screenshot
            query: Question about the screen
        
        Returns:
            VisionResult with answer
        """
        if not self.available:
            return VisionResult(
                description="Vision model not available",
                confidence=0.0
            )
        
        try:
            # Prepare query with image
            query_text = f"<img>{image_path}</img>{query}"
            
            # Generate response
            response, _ = self.model.chat(
                self.tokenizer,
                query=query_text,
                history=None
            )
            
            return VisionResult(
                description=response,
                confidence=0.85
            )
            
        except Exception as e:
            print(f"⚠️ Vision analysis failed: {e}")
            return VisionResult(
                description=f"Error: {e}",
                confidence=0.0
            )
    
    def find_icon(
        self,
        image_path: str,
        icon_description: str
    ) -> VisionResult:
        """
        Find icon/button on screen by description.
        
        Args:
            image_path: Path to screenshot
            icon_description: What to find (e.g., "send button", "paper plane icon")
        
        Returns:
            VisionResult with coordinates
        """
        
        prompt = f"""Analyze this mobile app screenshot (resolution: {self.screen_width}x{self.screen_height}).

Find the {icon_description}.

Respond with JSON in this format:
{{
    "found": true/false,
    "description": "what you see",
    "x": pixel_x_coordinate,
    "y": pixel_y_coordinate,
    "confidence": 0-100
}}

Rules:
- x must be between 0 and {self.screen_width}
- y must be between 0 and {self.screen_height}
- If not found, set found=false and omit x,y
- Be precise with coordinates"""

        result = self.analyze_screen(image_path, prompt)
        
        # Parse JSON response
        try:
            # Qwen-VL might return markdown-wrapped JSON
            response_text = result.description
            
            # Extract JSON
            if "```json" in response_text:
                json_text = response_text.split("```json")[1].split("```")[0]
            elif "```" in response_text:
                json_text = response_text.split("```")[1].split("```")[0]
            else:
                json_text = response_text
            
            data = json.loads(json_text.strip())
            
            if data.get('found', False):
                return VisionResult(
                    description=data.get('description', icon_description),
                    coordinates=(data.get('x', 0), data.get('y', 0)),
                    confidence=data.get('confidence', 50) / 100.0
                )
            else:
                return VisionResult(
                    description=f"Could not find: {icon_description}",
                    confidence=0.0
                )
        
        except json.JSONDecodeError:
            # Fallback: parse natural language
            return VisionResult(
                description=result.description,
                confidence=0.3
            )
    
    def find_all_icons(
        self,
        image_path: str,
        max_items: int = 10
    ) -> VisionResult:
        """
        Find all interactive elements on screen.
        
        Returns:
            VisionResult with list of elements
        """
        
        prompt = f"""Analyze this mobile app screenshot.

List ALL interactive elements (buttons, icons, tappable areas).

For each element, provide:
- Type (button, icon, text field, etc.)
- Description (what it looks like)
- Purpose (what it does)
- Location (approximate x, y coordinates)

Return as JSON array:
[
    {{
        "type": "button",
        "description": "blue send icon",
        "purpose": "send message",
        "x": 980,
        "y": 1850
    }},
    ...
]

Screen size: {self.screen_width}x{self.screen_height}
Maximum {max_items} items."""

        result = self.analyze_screen(image_path, prompt)
        
        try:
            # Parse JSON array
            response_text = result.description
            
            if "```json" in response_text:
                json_text = response_text.split("```json")[1].split("```")[0]
            else:
                json_text = response_text
            
            elements = json.loads(json_text.strip())
            
            return VisionResult(
                description=f"Found {len(elements)} elements",
                elements=elements,
                confidence=0.8
            )
        
        except json.JSONDecodeError:
            return VisionResult(
                description=result.description,
                confidence=0.3
            )
    
    def describe_screen(self, image_path: str, detailed: bool = False) -> VisionResult:
        """
        Generate description of what's on screen.
        """
        
        if detailed:
            prompt = """Describe this mobile screen in detail:
1. What app is this?
2. What screen/page?
3. Main content visible
4. Interactive elements (buttons, icons)
5. Current state/mode

Be specific and organized."""
        else:
            prompt = """Briefly describe what's on this mobile screen:
- App name
- Main content (2-3 items)
- Key actions available

Keep under 100 words."""
        
        return self.analyze_screen(image_path, prompt)
    
    def answer_question(self, image_path: str, question: str) -> VisionResult:
        """
        Answer a specific question about the screen.
        """
        
        prompt = f"""Look at this mobile screen and answer:

{question}

Give a clear, concise answer based only on what you see."""

        return self.analyze_screen(image_path, prompt)
    
    # ===========================
    # Icon-Specific Methods
    # ===========================
    
    def find_send_button(self, image_path: str) -> VisionResult:
        """Find send button (common action)"""
        return self.find_icon(
            image_path,
            "send button or paper plane icon or arrow icon for sending"
        )
    
    def find_back_button(self, image_path: str) -> VisionResult:
        """Find back button"""
        return self.find_icon(
            image_path,
            "back button or left arrow or back navigation"
        )
    
    def find_menu_button(self, image_path: str) -> VisionResult:
        """Find menu button"""
        return self.find_icon(
            image_path,
            "menu button or three dots or hamburger menu"
        )
    
    def find_search_button(self, image_path: str) -> VisionResult:
        """Find search button"""
        return self.find_icon(
            image_path,
            "search icon or magnifying glass"
        )
    
    # ===========================
    # Context-Aware Analysis
    # ===========================
    
    def detect_app_mode(self, image_path: str, app: str) -> str:
        """
        Detect current mode of an app.
        
        Examples:
        - YouTube: normal, fullscreen, pip, theater
        - WhatsApp: chat, status, calls
        """
        
        prompt = f"""This is a {app} screenshot.

What mode/screen is it in?
Examples:
- YouTube: video player, home feed, search
- WhatsApp: chat screen, status, calls list
- Instagram: feed, stories, direct messages

Answer with just the mode name."""

        result = self.analyze_screen(image_path, prompt)
        return result.description.strip().lower()
    
    def is_element_visible(
        self,
        image_path: str,
        element_description: str
    ) -> bool:
        """
        Check if an element is currently visible.
        """
        
        prompt = f"""Is there a {element_description} visible on this screen?

Answer with just: yes or no"""

        result = self.analyze_screen(image_path, prompt)
        return 'yes' in result.description.lower()
    
    # ===========================
    # Multi-Frame Analysis
    # ===========================
    
    def compare_screens(
        self,
        before_image: str,
        after_image: str
    ) -> VisionResult:
        """
        Compare two screenshots to detect what changed.
        """
        
        # Analyze both
        before = self.analyze_screen(before_image, "Describe what's on screen")
        after = self.analyze_screen(after_image, "Describe what's on screen")
        
        # Create comparison
        comparison = f"""BEFORE: {before.description}

AFTER: {after.description}

What changed?"""
        
        return VisionResult(
            description=comparison,
            confidence=0.7
        )