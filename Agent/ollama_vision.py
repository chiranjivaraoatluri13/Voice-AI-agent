# =========================
# FILE: agent/ollama_vision.py
# =========================
"""
Ollama Vision — CONTINUOUS WATCHING MODE.

Instead of: command → screenshot → analyze → respond (10s)
Now:         background thread continuously screenshots + analyzes
             command → read cached analysis → respond (instant)

For element finding: still does a targeted query but uses
pre-warmed model (stays loaded in GPU memory).
"""

import json
import base64
import time
import threading
import os
import tempfile
from typing import Optional, Dict, Tuple, List
from dataclasses import dataclass, field

try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False


@dataclass
class VisionResult:
    description: str
    coordinates: Optional[Tuple[int, int]] = None
    confidence: float = 0.0
    elements: List[Dict] = field(default_factory=list)


class OllamaVision:
    """
    Vision model with background watching.
    
    Two modes:
    1. WATCH MODE (background): Continuously captures + analyzes screen
       - Screen description always fresh (< 3s old)
       - "what do you see?" is instant
    2. TARGETED MODE (on-demand): Find specific element
       - Uses pre-warmed model (already loaded in GPU)
       - Faster because model doesn't need cold-start
    """
    
    def __init__(self, model: str = "llava-phi3") -> None:
        self.available = OLLAMA_AVAILABLE
        self.model = model
        self.screen_width = 1080
        self.screen_height = 2400
        
        # Background watching state
        self._watch_thread: Optional[threading.Thread] = None
        self._watching = False
        self._watch_interval = 3.0  # seconds between captures
        self._last_description = ""
        self._last_description_time = 0
        self._last_screenshot_b64 = ""
        self._last_screenshot_time = 0
        self._screenshot_lock = threading.Lock()
        self._adb = None  # Set by start_watching()
        
        # Screenshot path
        self._screenshot_path = os.path.join(tempfile.gettempdir(), "vision_watch.png")
        
        if self.available:
            self._check_model()
    
    def _check_model(self) -> None:
        try:
            models = ollama.list()
            model_names = [m.get('name', '') if isinstance(m, dict) else str(m) 
                          for m in models.get('models', [])]
            if not any(self.model in name for name in model_names):
                print(f"⚠️ Model '{self.model}' not found. Run: ollama pull {self.model}")
                self.available = False
        except Exception as e:
            print(f"⚠️ Ollama not running: {e}")
            self.available = False
    
    def set_screen_size(self, w: int, h: int) -> None:
        self.screen_width = w
        self.screen_height = h
    
    # =========================================================
    # BACKGROUND WATCHING
    # =========================================================
    def start_watching(self, adb) -> None:
        """Initialize vision with ADB reference. Warm up model in background."""
        if not self.available:
            return
        self._adb = adb
        # Only warm up model (HTTP call, safe for threads)
        # NO background ADB calls — causes EOFError on Windows
        threading.Thread(target=self._warmup, daemon=True).start()
        print("👁️ Vision ready (model warming up...)")
    
    def stop_watching(self) -> None:
        """Cleanup (no-op now since no bg thread)."""
        pass
    
    def _warmup(self) -> None:
        """Pre-load model into GPU memory so first real query is fast."""
        try:
            ollama.chat(model=self.model, messages=[{
                'role': 'user', 'content': 'hi', 'images': []
            }], options={'num_predict': 1})
            print("👁️ Vision model warmed up")
        except Exception:
            pass
    
    def capture_screenshot_b64(self) -> str:
        """Capture screenshot and return as base64. Cached for 2s."""
        now = time.time()
        with self._screenshot_lock:
            if (now - self._last_screenshot_time) < 2.0 and self._last_screenshot_b64:
                return self._last_screenshot_b64
        
        if not self._adb:
            return ""
        try:
            self._adb.run(["shell", "screencap", "-p", "/sdcard/screenshot.png"])
            self._adb.run(["pull", "/sdcard/screenshot.png", self._screenshot_path])
            with open(self._screenshot_path, 'rb') as f:
                b64 = base64.b64encode(f.read()).decode('utf-8')
            with self._screenshot_lock:
                self._last_screenshot_b64 = b64
                self._last_screenshot_time = time.time()
            return b64
        except Exception:
            return ""
    
    # =========================================================
    # CORE VISION (uses pre-cached screenshot when possible)
    # =========================================================
    def analyze_image(self, image_path_or_b64: str, prompt: str,
                      temperature: float = 0.1, is_b64: bool = False) -> VisionResult:
        if not self.available:
            return VisionResult(description="Vision not available", confidence=0.0)
        
        try:
            if is_b64:
                image_data = image_path_or_b64
            else:
                with open(image_path_or_b64, 'rb') as f:
                    image_data = base64.b64encode(f.read()).decode('utf-8')
            
            response = ollama.chat(
                model=self.model,
                messages=[{
                    'role': 'user',
                    'content': prompt,
                    'images': [image_data]
                }],
                options={
                    'temperature': temperature,
                    'num_predict': 200,  # Limit output length for speed
                }
            )
            content = response['message']['content'].strip()
            return VisionResult(description=content, confidence=0.85)
        except Exception as e:
            return VisionResult(description=f"Error: {e}", confidence=0.0)
    
    def find_element(self, image_path_or_b64: str, description: str,
                     is_b64: bool = False) -> VisionResult:
        """Find element by text OR icon - uses cached screenshot if available."""
        # Enhanced prompt: asks for text, icons, buttons, AND visual features
        prompt = f"""Find "{description}" on this mobile screen ({self.screen_width}x{self.screen_height}).

Look for:
1. Text/labels containing these words
2. Buttons/icons with matching appearance
3. Visual elements (colored buttons, badges, checkmarks)

For "{description}", describe:
- Is it text label? Icon? Colored button?
- Location: top/middle/bottom, left/center/right
- Color/appearance if relevant
- Confidence level

Reply ONLY with JSON: {{"found":true,"x":123,"y":456,"element_type":"text/button/icon/other","description":"what you found"}}
If not found: {{"found":false,"reason":"..."}}"""

        result = self.analyze_image(image_path_or_b64, prompt, 0.1, is_b64)
        
        try:
            data = json.loads(result.description)
            if data.get('found'):
                return VisionResult(
                    description=f"{data.get('element_type', 'element')}: {data.get('description', description)}",
                    coordinates=(data.get('x', 0), data.get('y', 0)),
                    confidence=0.8
                )
        except json.JSONDecodeError:
            coords = self._extract_coords(result.description)
            if coords:
                return VisionResult(description=description, coordinates=coords, confidence=0.6)
        
        return VisionResult(description=result.description, confidence=0.2)
    
    def find_element_fast(self, description: str) -> VisionResult:
        """Find element using cached screenshot. Captures if needed."""
        b64 = self.capture_screenshot_b64()
        if not b64:
            return VisionResult(description="No screenshot available", confidence=0.0)
        return self.find_element(b64, description, is_b64=True)
    
    def describe_screen(self, image_path: str = None, detailed: bool = False) -> VisionResult:
        if not self.available:
            return VisionResult(description="Vision not available", confidence=0.0)
        
        # Enhanced prompt to describe icons, buttons, AND text
        prompt = """Describe this mobile screen:
- App name or what it shows
- Main visual elements (icons, buttons, badges, images)
- Text labels and their locations
- Available actions (what can be tapped?)
Under 100 words."""
        
        if detailed:
            prompt = """Detailed screen description:
- App/content type
- Layout (top/middle/bottom sections)
- Icons with descriptions (subscribe, share, menu, settings, etc.)
- Text, labels, buttons
- Colors and visual state
- Interactive elements location"""
        
        if image_path:
            return self.analyze_image(image_path, prompt, 0.3)
        
        b64 = self.capture_screenshot_b64()
        if b64:
            return self.analyze_image(b64, prompt, 0.3, is_b64=True)
        return VisionResult(description="No screenshot", confidence=0.0)
    
    def describe_screen_fast(self) -> str:
        """Get screen description. Uses cached screenshot."""
        if self._last_description and (time.time() - self._last_description_time) < 5.0:
            return self._last_description
        result = self.describe_screen()
        self._last_description = result.description
        self._last_description_time = time.time()
        return result.description
    
    def answer_question(self, image_path: str, question: str) -> VisionResult:
        prompt = f"Question about this mobile screen: {question}\nAnswer concisely."
        return self.analyze_image(image_path, prompt, 0.2)
    
    def find_icon_by_appearance(self, description: str) -> VisionResult:
        """
        Find element by visual appearance (icon, color, button type).
        Better for non-text UI elements like colored buttons, badges, etc.
        """
        b64 = self.capture_screenshot_b64()
        if not b64:
            return VisionResult(description="No screenshot available", confidence=0.0)
        
        # Specialized prompt for visual/icon-based elements
        prompt = f"""Find a {description} on this mobile screen ({self.screen_width}x{self.screen_height}).

This might be:
- An icon (colored symbol, image)
- A button with specific appearance or color
- A badge or notification
- Visual indicator or symbol

Describe what you found and give coordinates.
Reply ONLY with JSON: {{"found":true,"x":123,"y":456,"element_type":"icon/button/badge/other","visual_description":"colored button, heart icon, etc."}}
If not found: {{"found":false}}"""
        
        result = self.analyze_image(b64, prompt, 0.1, is_b64=True)
        
        try:
            data = json.loads(result.description)
            if data.get('found'):
                return VisionResult(
                    description=f"Found {data.get('element_type', 'element')}: {data.get('visual_description', description)}",
                    coordinates=(data.get('x', 0), data.get('y', 0)),
                    confidence=0.75
                )
        except json.JSONDecodeError:
            coords = self._extract_coords(result.description)
            if coords:
                return VisionResult(description=description, coordinates=coords, confidence=0.5)
        
        return VisionResult(description=result.description, confidence=0.2)
    
    def find_nth_item(self, image_path: str, item_type: str, position: int) -> VisionResult:
        ords = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth"}
        return self.find_element(image_path, f"the {ords.get(position, f'{position}th')} {item_type}")
    
    # =========================================================
    # Utilities
    # =========================================================
    def _extract_coords(self, text: str) -> Optional[Tuple[int, int]]:
        import re
        patterns = [
            r'coordinates?\s*\(?\s*(\d+)\s*,\s*(\d+)',
            r'"x"\s*:\s*(\d+).*?"y"\s*:\s*(\d+)',
            r'x\s*[:=]\s*(\d+).*?y\s*[:=]\s*(\d+)',
            r'\((\d+)\s*,\s*(\d+)\)',
        ]
        for p in patterns:
            m = re.search(p, text, re.IGNORECASE | re.DOTALL)
            if m:
                x, y = int(m.group(1)), int(m.group(2))
                if 0 <= x <= self.screen_width and 0 <= y <= self.screen_height:
                    return (x, y)
        return None
    
    def validate_coordinates(self, x: int, y: int) -> bool:
        return 0 <= x <= self.screen_width and 0 <= y <= self.screen_height
