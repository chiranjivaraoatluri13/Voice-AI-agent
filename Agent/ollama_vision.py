# =========================
# FILE: agent/ollama_vision.py
# =========================
"""
Ollama Vision integration for complex visual understanding.
Uses local LLaVA models for image analysis and element detection.
"""

import json
import base64
from typing import Optional, Dict, Tuple, List
from dataclasses import dataclass

try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False
    print("âš ï¸ ollama not installed. Vision features disabled.")
    print("   Install: pip install ollama")
    print("   Then: ollama pull llava-phi3")


@dataclass
class VisionResult:
    """Result from vision model"""
    
    description: str
    coordinates: Optional[Tuple[int, int]] = None
    confidence: float = 0.0
    elements: List[Dict] = None  # For multi-element responses
    
    def __post_init__(self):
        if self.elements is None:
            self.elements = []


class OllamaVision:
    """
    Local vision model integration using Ollama.
    """
    
    def __init__(self, model: str = "llava-phi3") -> None:
        self.available = OLLAMA_AVAILABLE
        self.model = model
        self.screen_width = 1080  # Default, update from device
        self.screen_height = 2400  # Default, update from device
        
        if self.available:
            self._check_model_availability()
    
    def _check_model_availability(self) -> None:
        """Check if the model is pulled and ready"""
        try:
            models = ollama.list()
            model_names = [m['name'] for m in models.get('models', [])]
            
            if not any(self.model in name for name in model_names):
                print(f"âš ï¸ Model '{self.model}' not found locally.")
                print(f"   Run: ollama pull {self.model}")
                print(f"   This will download ~3GB")
                self.available = False
        except Exception as e:
            print(f"âš ï¸ Could not connect to Ollama: {e}")
            print("   Is Ollama running? Start with: ollama serve")
            self.available = False
    
    def set_screen_size(self, width: int, height: int) -> None:
        """Update screen dimensions for coordinate mapping"""
        self.screen_width = width
        self.screen_height = height
    
    # -------------------------
    # Core Vision Methods
    # -------------------------
    def analyze_image(
        self,
        image_path: str,
        prompt: str,
        temperature: float = 0.1
    ) -> VisionResult:
        """
        Send image + prompt to vision model.
        
        Args:
            image_path: Path to screenshot
            prompt: Question/instruction for the model
            temperature: Randomness (0=deterministic, 1=creative)
        
        Returns:
            VisionResult with description and optional coordinates
        """
        if not self.available:
            return VisionResult(
                description="Vision model not available",
                confidence=0.0
            )
        
        try:
            # Read and encode image
            with open(image_path, 'rb') as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')
            
            # Query Ollama
            response = ollama.chat(
                model=self.model,
                messages=[{
                    'role': 'user',
                    'content': prompt,
                    'images': [image_data]
                }],
                options={
                    'temperature': temperature,
                }
            )
            
            content = response['message']['content'].strip()
            
            return VisionResult(
                description=content,
                confidence=0.85  # Ollama doesn't provide confidence
            )
            
        except Exception as e:
            print(f"âš ï¸ Vision analysis failed: {e}")
            return VisionResult(
                description=f"Error: {e}",
                confidence=0.0
            )
    
    # -------------------------
    # Element Detection
    # -------------------------
    def find_element(
        self,
        image_path: str,
        description: str
    ) -> VisionResult:
        """
        Find element on screen by description.
        
        Args:
            image_path: Path to screenshot
            description: What to find (e.g., "Subscribe button", "first video", "red car")
        
        Returns:
            VisionResult with coordinates
        """
        prompt = f"""You are analyzing a mobile app screenshot (resolution: {self.screen_width}x{self.screen_height}).

Find the element: "{description}"

Respond ONLY with valid JSON in this exact format:
{{
    "found": true/false,
    "x": pixel_x_coordinate,
    "y": pixel_y_coordinate,
    "confidence": 0-100,
    "description": "brief description of what you found"
}}

Rules:
- x must be between 0 and {self.screen_width}
- y must be between 0 and {self.screen_height}
- If not found, set found=false and omit x,y
- Return ONLY the JSON, no other text"""

        result = self.analyze_image(image_path, prompt, temperature=0.1)
        
        # Parse JSON response
        try:
            data = json.loads(result.description)
            
            if data.get('found', False):
                return VisionResult(
                    description=data.get('description', description),
                    coordinates=(data.get('x', 0), data.get('y', 0)),
                    confidence=data.get('confidence', 50) / 100.0
                )
            else:
                return VisionResult(
                    description=f"Could not find: {description}",
                    confidence=0.0
                )
        
        except json.JSONDecodeError:
            # Fallback: try to extract coordinates from text
            coords = self._extract_coordinates_from_text(result.description)
            if coords:
                return VisionResult(
                    description=description,
                    coordinates=coords,
                    confidence=0.6
                )
            
            return VisionResult(
                description=result.description,
                confidence=0.3
            )
    
    def find_multiple(
        self,
        image_path: str,
        description: str,
        max_items: int = 5
    ) -> VisionResult:
        """
        Find multiple elements on screen.
        
        Args:
            image_path: Path to screenshot
            description: What to find (e.g., "all videos", "all buttons")
            max_items: Maximum number of items to return
        
        Returns:
            VisionResult with list of elements
        """
        prompt = f"""You are analyzing a mobile app screenshot (resolution: {self.screen_width}x{self.screen_height}).

Find up to {max_items} instances of: "{description}"

Respond ONLY with valid JSON array in this exact format:
[
    {{
        "index": 1,
        "x": pixel_x,
        "y": pixel_y,
        "description": "brief description"
    }},
    ...
]

Rules:
- x must be between 0 and {self.screen_width}
- y must be between 0 and {self.screen_height}
- Sort by visual order (top to bottom, left to right)
- Return ONLY the JSON array, no other text"""

        result = self.analyze_image(image_path, prompt, temperature=0.1)
        
        try:
            elements = json.loads(result.description)
            
            return VisionResult(
                description=f"Found {len(elements)} items",
                elements=elements,
                confidence=0.8
            )
        
        except json.JSONDecodeError:
            return VisionResult(
                description=result.description,
                confidence=0.3
            )
    
    # -------------------------
    # Screen Understanding
    # -------------------------
    def describe_screen(self, image_path: str, detailed: bool = False) -> VisionResult:
        """
        Generate natural language description of screen.
        
        Args:
            image_path: Path to screenshot
            detailed: If True, provide detailed description
        
        Returns:
            VisionResult with description
        """
        if detailed:
            prompt = """Analyze this mobile app screenshot in detail.

Provide a structured description:
1. App name (if visible)
2. Main content (list key elements)
3. Interactive elements (buttons, icons, links)
4. Notable visual elements
5. Current state/context

Be concise but thorough."""
        else:
            prompt = """Briefly describe what you see on this mobile screen.

Include:
- App name
- Main content (2-3 key items)
- Primary actions available

Keep it under 100 words."""
        
        return self.analyze_image(image_path, prompt, temperature=0.3)
    
    def answer_question(self, image_path: str, question: str) -> VisionResult:
        """
        Answer a question about the screen.
        
        Args:
            image_path: Path to screenshot
            question: Question to answer
        
        Returns:
            VisionResult with answer
        """
        prompt = f"""You are analyzing a mobile app screenshot.

Question: {question}

Provide a clear, concise answer based only on what you see in the image.
If you cannot answer based on the image, say so."""

        return self.analyze_image(image_path, prompt, temperature=0.2)
    
    # -------------------------
    # Position-based queries
    # -------------------------
    def find_nth_item(
        self,
        image_path: str,
        item_type: str,
        position: int
    ) -> VisionResult:
        """
        Find the Nth item of a type (e.g., "second video", "third button").
        
        Args:
            image_path: Path to screenshot
            item_type: Type of item (e.g., "video", "button", "post")
            position: Position (1 = first, 2 = second, etc.)
        
        Returns:
            VisionResult with coordinates
        """
        ordinals = {
            1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth",
            6: "sixth", 7: "seventh", 8: "eighth", 9: "ninth", 10: "tenth"
        }
        
        ordinal = ordinals.get(position, f"{position}th")
        
        return self.find_element(image_path, f"the {ordinal} {item_type}")
    
    # -------------------------
    # Visual search (color, pattern, etc.)
    # -------------------------
    def find_by_visual(
        self,
        image_path: str,
        visual_description: str
    ) -> VisionResult:
        """
        Find element by visual characteristics.
        
        Args:
            image_path: Path to screenshot
            visual_description: Visual description (e.g., "red button", "car image")
        
        Returns:
            VisionResult with coordinates
        """
        return self.find_element(image_path, visual_description)
    
    # -------------------------
    # Utilities
    # -------------------------
    def _extract_coordinates_from_text(self, text: str) -> Optional[Tuple[int, int]]:
        """
        Try to extract (x, y) coordinates from natural language response.
        Fallback when JSON parsing fails.
        """
        import re
        
        # Pattern: "at coordinates (x, y)" or "position x, y"
        patterns = [
            r'coordinates?\s*\(?\s*(\d+)\s*,\s*(\d+)\s*\)?',
            r'position\s*\(?\s*(\d+)\s*,\s*(\d+)\s*\)?',
            r'x\s*[:=]\s*(\d+).*?y\s*[:=]\s*(\d+)',
            r'\((\d+)\s*,\s*(\d+)\)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                x, y = int(match.group(1)), int(match.group(2))
                
                # Validate coordinates
                if 0 <= x <= self.screen_width and 0 <= y <= self.screen_height:
                    return (x, y)
        
        return None
    
    def validate_coordinates(self, x: int, y: int) -> bool:
        """Check if coordinates are within screen bounds"""
        return 0 <= x <= self.screen_width and 0 <= y <= self.screen_height
