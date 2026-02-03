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
    print("⚠️ ollama not installed. Vision features disabled.")
    print("   Install: pip install ollama")
    print("   Then: ollama pull llava-phi3")


@dataclass
class VisionResult:
    """Result from vision model"""
    description: str
    coordinates: Optional[Tuple[int, int]] = None
    confidence: float = 0.0
    elements: List[Dict] = None

    def __post_init__(self):
        if self.elements is None:
            self.elements = []


class OllamaVision:
    """
    Local vision model integration using Ollama.
    """

    def __init__(self, model: str = "llava-phi3:latest") -> None:
        self.available = OLLAMA_AVAILABLE
        self.model = model
        self.screen_width = 1080
        self.screen_height = 2400

        if self.available:
            self._check_model_availability()

    # =========================
    # FIXED MODEL CHECK
    # =========================
    def _check_model_availability(self) -> None:
        """Check if the model is pulled and ready (new Ollama client compatible)."""
        try:
            resp = ollama.list()
            model_names = []

            # New Ollama Python client (resp.models = list of Model objects)
            if hasattr(resp, "models"):
                for m in resp.models:
                    name = getattr(m, "model", None) or getattr(m, "name", None)
                    if name:
                        model_names.append(name)

            # Older client (dict-based)
            elif isinstance(resp, dict):
                for m in resp.get("models", []):
                    if isinstance(m, dict):
                        name = m.get("name") or m.get("model")
                        if name:
                            model_names.append(name)

            wanted = self.model.split(":")[0]
            if not any(wanted in name for name in model_names):
                print(f"⚠️ Vision model '{self.model}' not found.")
                print(f"   Installed models: {model_names}")
                print(f"   Run: ollama pull {self.model}")
                self.available = False

        except Exception as e:
            print(f"⚠️ Could not query Ollama: {e}")
            print("   Is Ollama running? Try: ollama list")
            self.available = False

    # =========================
    # CONFIG
    # =========================
    def set_screen_size(self, width: int, height: int) -> None:
        self.screen_width = width
        self.screen_height = height

    # =========================
    # CORE VISION
    # =========================
    def analyze_image(
        self,
        image_path: str,
        prompt: str,
        temperature: float = 0.1
    ) -> VisionResult:

        if not self.available:
            return VisionResult(
                description="Vision model not available",
                confidence=0.0
            )

        try:
            with open(image_path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode("utf-8")

            response = ollama.chat(
                model=self.model,
                messages=[{
                    "role": "user",
                    "content": prompt,
                    "images": [image_data]
                }],
                options={"temperature": temperature},
            )

            content = response["message"]["content"].strip()

            return VisionResult(
                description=content,
                confidence=0.85
            )

        except Exception as e:
            print(f"⚠️ Vision analysis failed: {e}")
            return VisionResult(
                description=str(e),
                confidence=0.0
            )

    # =========================
    # ELEMENT FINDING
    # =========================
    def find_element(self, image_path: str, description: str) -> VisionResult:
        prompt = f"""
You are analyzing a mobile app screenshot ({self.screen_width}x{self.screen_height}).

Find the element: "{description}"

Respond ONLY with valid JSON:
{{
  "found": true/false,
  "x": number,
  "y": number,
  "confidence": 0-100,
  "description": "what you found"
}}
"""

        result = self.analyze_image(image_path, prompt)

        try:
            data = json.loads(result.description)
            if data.get("found"):
                return VisionResult(
                    description=data.get("description", description),
                    coordinates=(data["x"], data["y"]),
                    confidence=data.get("confidence", 50) / 100.0
                )
            return VisionResult(description=f"Not found: {description}")

        except Exception:
            return VisionResult(description=result.description, confidence=0.3)

    # =========================
    # SCREEN DESCRIPTION
    # =========================
    def describe_screen(self, image_path: str, detailed: bool = False) -> VisionResult:
        prompt = (
            "Describe this mobile screen in detail."
            if detailed
            else "Briefly describe what you see on this mobile screen."
        )
        return self.analyze_image(image_path, prompt, temperature=0.3)

    # =========================
    # Q&A
    # =========================
    def answer_question(self, image_path: str, question: str) -> VisionResult:
        prompt = f"Answer this question based on the image: {question}"
        return self.analyze_image(image_path, prompt, temperature=0.2)
