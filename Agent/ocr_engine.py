# =========================
# FILE: agent/ocr_engine.py
# =========================
"""
OCR engine using Tesseract for text extraction.
Fallback when UI Automator doesn't capture text elements.
"""

import re
from typing import List, Tuple, Optional
from dataclasses import dataclass
from PIL import Image
import numpy as np
import platform
import os

try:
    import pytesseract
    
    # ===== WINDOWS CONFIGURATION =====
    # Set Tesseract path explicitly for Windows
    if platform.system() == "Windows":
        # Try common installation paths
        possible_paths = [
            r'C:\Program Files\Tesseract-OCR\tesseract.exe',
            r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
            os.path.expanduser(r'~\AppData\Local\Programs\Tesseract-OCR\tesseract.exe'),
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                pytesseract.pytesseract.tesseract_cmd = path
                print(f"âœ… Tesseract found at: {path}")
                break
        else:
            print("âš ï¸ Tesseract not found in standard locations.")
            print("   Please set path manually in ocr_engine.py")
            print("   Or install from: https://github.com/UB-Mannheim/tesseract/wiki")
    # ===== END WINDOWS CONFIGURATION =====
    
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False
    print("âš ï¸ pytesseract not installed. OCR features disabled.")
    print("   Install: pip install pytesseract")


@dataclass
class OCRMatch:
    """Represents text found via OCR"""
    
    text: str
    confidence: float
    bounds: Tuple[int, int, int, int]  # (left, top, width, height)
    
    @property
    def center(self) -> Tuple[int, int]:
        """Get center coordinates for tapping"""
        left, top, width, height = self.bounds
        return (left + width // 2, top + height // 2)
    
    @property
    def area(self) -> int:
        return self.bounds[2] * self.bounds[3]
    
    def __repr__(self) -> str:
        return f"OCRMatch(text='{self.text}', conf={self.confidence:.2f}, bounds={self.bounds})"


class OCREngine:
    """
    Text extraction and search using Tesseract OCR.
    """
    
    def __init__(self) -> None:
        self.available = TESSERACT_AVAILABLE
        self.last_screenshot: Optional[Image.Image] = None
        self.last_ocr_data: Optional[dict] = None
    
    # -------------------------
    # OCR Extraction
    # -------------------------
    def extract_text(self, image_path: str, force_refresh: bool = False) -> List[OCRMatch]:
        """
        Extract all text from image with bounding boxes.
        
        Args:
            image_path: Path to screenshot
            force_refresh: Force re-run OCR (skip cache)
        
        Returns:
            List of OCRMatch objects
        """
        if not self.available:
            print("âš ï¸ OCR not available (pytesseract not installed)")
            return []
        
        try:
            # Load image
            image = Image.open(image_path)
            
            # Check cache
            if not force_refresh and self.last_screenshot == image:
                return self._parse_ocr_data(self.last_ocr_data)
            
            # Run OCR with bounding box data
            ocr_data = pytesseract.image_to_data(
                image,
                output_type=pytesseract.Output.DICT,
                config='--psm 11'  # Sparse text mode
            )
            
            # Cache results
            self.last_screenshot = image
            self.last_ocr_data = ocr_data
            
            return self._parse_ocr_data(ocr_data)
            
        except Exception as e:
            print(f"âš ï¸ OCR extraction failed: {e}")
            return []
    
    def _parse_ocr_data(self, ocr_data: dict) -> List[OCRMatch]:
        """Parse Tesseract output into OCRMatch objects"""
        if not ocr_data:
            return []
        
        matches = []
        n_boxes = len(ocr_data['text'])
        
        for i in range(n_boxes):
            text = ocr_data['text'][i].strip()
            conf = int(ocr_data['conf'][i])
            
            # Skip empty or low-confidence results
            if not text or conf < 30:
                continue
            
            match = OCRMatch(
                text=text,
                confidence=conf / 100.0,
                bounds=(
                    ocr_data['left'][i],
                    ocr_data['top'][i],
                    ocr_data['width'][i],
                    ocr_data['height'][i]
                )
            )
            
            matches.append(match)
        
        return matches
    
    # -------------------------
    # Text Search
    # -------------------------
    def find_text(
        self, 
        image_path: str, 
        query: str, 
        exact: bool = False,
        min_confidence: float = 0.6
    ) -> List[OCRMatch]:
        """
        Find text on screen matching query.
        
        Args:
            image_path: Path to screenshot
            query: Text to search for
            exact: If True, match exactly; if False, substring match
            min_confidence: Minimum OCR confidence (0-1)
        
        Returns:
            List of matching OCRMatch objects, sorted by confidence
        """
        matches = self.extract_text(image_path)
        
        query_lower = query.lower()
        results = []
        
        for match in matches:
            if match.confidence < min_confidence:
                continue
            
            text_lower = match.text.lower()
            
            if exact:
                if text_lower == query_lower:
                    results.append(match)
            else:
                if query_lower in text_lower:
                    results.append(match)
        
        # Sort by confidence descending
        results.sort(key=lambda m: m.confidence, reverse=True)
        
        return results
    
    def find_text_fuzzy(
        self,
        image_path: str,
        query: str,
        threshold: float = 0.7,
        min_confidence: float = 0.6
    ) -> List[Tuple[float, OCRMatch]]:
        """
        Fuzzy text search using similarity scoring.
        
        Returns:
            List of (similarity_score, OCRMatch) tuples, sorted by score
        """
        from difflib import SequenceMatcher
        
        matches = self.extract_text(image_path)
        scored_results = []
        
        query_lower = query.lower()
        
        for match in matches:
            if match.confidence < min_confidence:
                continue
            
            text_lower = match.text.lower()
            
            # Calculate similarity
            similarity = SequenceMatcher(None, query_lower, text_lower).ratio()
            
            if similarity >= threshold:
                scored_results.append((similarity, match))
        
        # Sort by similarity descending
        scored_results.sort(key=lambda x: x[0], reverse=True)
        
        return scored_results
    
    # -------------------------
    # Region-based search
    # -------------------------
    def find_in_region(
        self,
        image_path: str,
        region: str,  # 'top', 'bottom', 'left', 'right', 'center'
        query: Optional[str] = None
    ) -> List[OCRMatch]:
        """
        Find text in a specific screen region.
        """
        matches = self.extract_text(image_path)
        
        if not matches:
            return []
        
        # Get image dimensions
        image = Image.open(image_path)
        img_width, img_height = image.size
        
        # Define region filters
        regions = {
            "top": lambda m: m.bounds[1] < img_height * 0.25,
            "bottom": lambda m: m.bounds[1] > img_height * 0.75,
            "left": lambda m: m.bounds[0] < img_width * 0.25,
            "right": lambda m: m.bounds[0] > img_width * 0.75,
            "center": lambda m: (
                img_width * 0.25 < m.bounds[0] < img_width * 0.75 and
                img_height * 0.25 < m.bounds[1] < img_height * 0.75
            ),
        }
        
        filter_func = regions.get(region.lower())
        if not filter_func:
            return []
        
        results = [m for m in matches if filter_func(m)]
        
        # Additional text filter if query provided
        if query:
            query_lower = query.lower()
            results = [m for m in results if query_lower in m.text.lower()]
        
        return results
    
    # -------------------------
    # Screen Description
    # -------------------------
    def describe_screen(self, image_path: str, max_items: int = 20) -> str:
        """
        Generate text description of screen based on OCR.
        """
        matches = self.extract_text(image_path)
        
        if not matches:
            return "No text detected on screen"
        
        # Filter out very small text (likely noise)
        significant_matches = [
            m for m in matches 
            if m.area > 100 and m.confidence > 0.7
        ]
        
        # Sort by vertical position (top to bottom)
        significant_matches.sort(key=lambda m: m.bounds[1])
        
        description = f"OCR Analysis:\n"
        description += f"- Detected {len(significant_matches)} text elements\n"
        description += f"- Text content:\n"
        
        for i, match in enumerate(significant_matches[:max_items], 1):
            description += f"  {i}. {match.text} (conf: {match.confidence:.0%})\n"
        
        if len(significant_matches) > max_items:
            description += f"  ... and {len(significant_matches) - max_items} more\n"
        
        return description
    
    # -------------------------
    # Utilities
    # -------------------------
    def preprocess_image(self, image_path: str, output_path: str) -> None:
        """
        Preprocess image for better OCR accuracy.
        - Convert to grayscale
        - Increase contrast
        - Remove noise
        """
        try:
            import cv2
            
            # Read image
            img = cv2.imread(image_path)
            
            # Convert to grayscale
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            
            # Apply thresholding
            _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            
            # Denoise
            denoised = cv2.fastNlMeansDenoising(thresh)
            
            # Save
            cv2.imwrite(output_path, denoised)
            
        except ImportError:
            print("âš ï¸ opencv-python not installed. Skipping preprocessing.")
            print("   Install: pip install opencv-python")
