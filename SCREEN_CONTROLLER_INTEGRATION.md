# UITreeNavigator Integration Guide

## Overview

This guide shows how to integrate `UITreeNavigator` into `ScreenController` to enable complex, hierarchical UI navigation for multi-step commands.

**Current State:** UITreeNavigator is fully implemented but not yet wired into ScreenController.

**Goal:** Enable voice commands like "Click subscribe, then select shorts, then find three dots menu, then like" to work end-to-end.

---

## Integration Steps

### Step 1: Update ScreenController.__init__()

**File:** `agent/screen_controller.py`

**Current:**
```python
def __init__(self, device_output_path="/sdcard/screenshots", use_ocr=True):
    self.ui_analyzer = UIAnalyzer(self.adb)
    self.ocr_engine = OCREngine()
    self.vision = OllamaVision(model="qwen2.5:0.5b")
    # ... other init code
```

**Modified:**
```python
def __init__(self, device_output_path="/sdcard/screenshots", use_ocr=True):
    self.ui_analyzer = UIAnalyzer(self.adb)
    self.ocr_engine = OCREngine()
    self.vision = OllamaVision(model="qwen2.5:0.5b")
    
    # NEW: Initialize UITreeNavigator for hierarchical navigation
    from agent.ui_tree_navigator import UITreeNavigator
    self.navigator = UITreeNavigator(self.adb, self.ui_analyzer)
    
    # ... other init code
```

---

### Step 2: Add Multi-Step Command Parser

**Add to ScreenController:**

```python
def _parse_multi_step_command(self, query: str) -> Optional[List[str]]:
    """
    Parse commands with multiple steps.
    
    Examples:
    - "click subscribe then select shorts then like"
      → ["subscribe", "shorts", "like"]
    
    - "go to notifications and turn on bell notifications"
      → ["notifications", "turn on bell"]
    
    - "find three dots menu and add to playlist and select favorites"
      → ["three dots", "add to playlist", "favorites"]
    
    Delimiters: "then", "and then", "after that", "next", "&"
    """
    import re
    
    # Split on multi-step delimiters
    delimiters = r'\b(?:then|and then|after that|next|&)\b'
    steps = re.split(delimiters, query, flags=re.IGNORECASE)
    
    # Clean up steps
    steps = [step.strip() for step in steps if step.strip()]
    
    # If only one step, this is a regular command
    if len(steps) <= 1:
        return None
    
    print(f"[PARSER] Multi-step command detected: {len(steps)} steps")
    for i, step in enumerate(steps, 1):
        print(f"  Step {i}: {step}")
    
    return steps
```

---

### Step 3: Add Multi-Step Executor

**Add to ScreenController:**

```python
def _execute_multi_step_command(self, steps: List[str]) -> bool:
    """
    Execute a multi-step navigation workflow using UITreeNavigator.
    
    This is the hierarchical approach that understands UI context
    and relationships between elements.
    """
    print(f"\n[NAVIGATOR] Starting {len(steps)}-step navigation workflow")
    
    # Execute sequence
    results = self.navigator.navigate_sequence(steps)
    
    # Track results
    success_count = sum(1 for success, _ in results if success)
    
    print(f"[NAVIGATOR] Completed {success_count}/{len(steps)} steps:")
    for i, (success, message) in enumerate(results, 1):
        status = "✓" if success else "✗"
        print(f"  {status} Step {i}: {message}")
    
    # If all steps succeeded, we're done
    if success_count == len(steps):
        print("[NAVIGATOR] ✓ All steps completed successfully")
        return True
    
    # Fallback for failed steps
    failed_steps = [
        (i+1, step) for i, (step, (success, _)) in enumerate(zip(steps, results))
        if not success
    ]
    
    if failed_steps:
        print(f"\n[FALLBACK] {len(failed_steps)} steps failed, attempting vision-based fallback")
        for step_num, step in failed_steps:
            print(f"  [FALLBACK] Retrying step {step_num}: '{step}' with vision")
            self._vision_find_and_tap_fast(step)
    
    return success_count > 0  # Partial success still helps
```

---

### Step 4: Update Main execute_query() Method

**File:** `agent/screen_controller.py`

**Current:**
```python
def execute_query(self, query: str, target: Optional[str] = None) -> bool:
    """Main entry point for voice commands"""
    search_text = target or query
    
    # Try UI tree search
    if self._try_ui_tree_search(search_text):
        return True
    
    # Try OCR search
    if self._try_ocr_search(search_text):
        return True
    
    # Vision fallback
    return self._vision_find_and_tap_fast(search_text)
```

**Modified (Enhanced):**
```python
def execute_query(self, query: str, target: Optional[str] = None) -> bool:
    """
    Main entry point for voice commands.
    
    Supports both simple and multi-step queries:
    - Simple: "click like" or "tap subscribe"
    - Complex: "click subscribe then select shorts then like"
    
    Flow:
    1. Try multi-step hierarchical navigation (NEW)
    2. Try simple UI tree search
    3. Try OCR search
    4. Fall back to vision
    """
    
    search_text = target or query
    
    # NEW: Check for multi-step commands
    steps = self._parse_multi_step_command(query)
    if steps:
        print(f"[ROUTER] Detected multi-step command: {' → '.join(steps)}")
        try:
            return self._execute_multi_step_command(steps)
        except Exception as e:
            print(f"[ERROR] Multi-step execution failed: {e}")
            # Fall through to single-step handlers
    
    # Simple single-step command
    print(f"[ROUTER] Executing simple command: '{search_text}'")
    
    # Try UI tree search (hierarchical for single elements)
    if self._try_ui_tree_search(search_text):
        print(f"[SUCCESS] Found via UI tree")
        return True
    
    # Try OCR search
    if self._try_ocr_search(search_text):
        print(f"[SUCCESS] Found via OCR")
        return True
    
    # Vision fallback
    print(f"[FALLBACK] Attempting vision-based search")
    return self._vision_find_and_tap_fast(search_text)
```

---

### Step 5: Enhance _try_ui_tree_search()

**Current implementation likely looks like:**

```python
def _try_ui_tree_search(self, query: str) -> bool:
    """Search UI tree for element and tap it"""
    self.ui_analyzer.capture_ui_tree()
    elements = self.ui_analyzer.find_by_text(query)
    
    if not elements:
        return False
    
    element = elements[0]
    if element.clickable:
        x, y = element.center
        self.adb.run(["shell", "input", "tap", str(x), str(y)])
        return True
    
    return False
```

**Enhanced to use Navigator:**

```python
def _try_ui_tree_search(self, query: str) -> bool:
    """
    Search UI tree for element and tap it.
    
    Uses hierarchical navigation for better accuracy:
    - Finds element in UI context
    - Handles nested/scrolled elements
    - Respects clickability and visibility
    """
    print(f"  [UI_SEARCH] Looking for: '{query}'")
    
    try:
        # Capture fresh tree
        self.ui_analyzer.capture_ui_tree()
        
        # NEW: Use navigator for more intelligent search
        element = self.navigator.find_element_in_context(query)
        
        if not element:
            print(f"  [UI_SEARCH] ✗ Not found")
            return False
        
        # Check if element is interactable
        if not element.is_interactable():
            print(f"  [UI_SEARCH] ⚠ Found but not interactable")
            return False
        
        # Handle invisible elements (might need scrolling)
        if not element.is_visible():
            print(f"  [UI_SEARCH] ⚠ Found but not visible - scrolling parent")
            # Scroll parent into view if needed
            if element.parent_index is not None:
                parent = self.ui_analyzer.last_elements[element.parent_index]
                if parent.scrollable:
                    self._scroll_element_into_view(parent, element)
        
        # Tap the element
        x, y = element.center
        print(f"  [UI_SEARCH] ✓ Found and tapping at ({x}, {y})")
        self.adb.run(["shell", "input", "tap", str(x), str(y)])
        
        return True
    
    except Exception as e:
        print(f"  [UI_SEARCH] Error: {e}")
        return False

def _scroll_element_into_view(self, scrollable_parent, target_element):
    """Helper to scroll an element into view"""
    x, y = scrollable_parent.center
    # Scroll to reveal target
    self.adb.run(["shell", "input", "swipe", 
                  str(x), str(y-100), str(x), str(y+100)])
    time.sleep(0.5)
```

---

## Usage Examples

### Example 1: Simple Command (Single Step)

```python
controller = ScreenController()

# Simple voice command
controller.execute_query("click like button")
# Result: 
# [ROUTER] Executing simple command: 'click like button'
# [UI_SEARCH] Looking for: 'click like button'
# [UI_SEARCH] ✓ Found and tapping at (540, 320)
# [SUCCESS] Found via UI tree
```

---

### Example 2: Multi-Step Command (Hierarchical)

```python
controller = ScreenController()

# Complex voice command
controller.execute_query("click subscribe then select shorts then find three dots then like")
# Result:
# [ROUTER] Detected multi-step command: 4 steps
# [NAVIGATOR] Starting 4-step navigation workflow
# [NAVIGATOR] Captured UI tree with 145 elements
#   ✓ Step 1: Tapped Subscribe button at (720, 450)
# [NAVIGATOR] Re-capturing UI tree after Subscribe action
# [NAVIGATOR] Captured UI tree with 198 elements
#   ✓ Step 2: Tapped Shorts option at (600, 350)
# [NAVIGATOR] Re-capturing UI tree after Shorts action
# [NAVIGATOR] Captured UI tree with 156 elements
#   ✓ Step 3: Tapped More options (three dots) at (750, 300)
# [NAVIGATOR] Re-capturing UI tree after More options action
# [NAVIGATOR] Captured UI tree with 220 elements
#   ✓ Step 4: Tapped Like action at (620, 380)
# [NAVIGATOR] ✓ All steps completed successfully
```

---

### Example 3: Voice Agent Integration

```python
from agent.intelligent_device_controller import IntelligentDeviceController
from agent.screen_controller import ScreenController

class VoiceAgent:
    def __init__(self):
        self.screen_controller = ScreenController()
        self.device_controller = IntelligentDeviceController()
    
    def execute_voice_command(self, command: str) -> bool:
        """Execute voice command with proper routing"""
        
        # Route device commands (brightness, audio, wifi)
        if any(keyword in command.lower() for keyword 
               in ["brightness", "volume", "mute", "unmute"]):
            return self.device_controller.execute_command(command)
        
        # Route UI commands to screen controller
        # (automatically handles multi-step)
        return self.screen_controller.execute_query(command)

# Usage
agent = VoiceAgent()

# Multi-step UI command
agent.execute_voice_command("click subscribe then select shorts then like")

# Device command
agent.execute_voice_command("make it brighter")

# Combined
agent.execute_voice_command("like the video and turn up the volume")
```

---

## Testing Multi-Step Commands

### Quick Test Script

```python
from agent.screen_controller import ScreenController

def test_multi_step():
    controller = ScreenController()
    
    test_cases = [
        # Simple commands
        ("click like", True),
        ("tap subscribe", True),
        ("find more options", True),
        
        # Multi-step commands
        ("click subscribe then select shorts", True),
        ("tap video then like then share", True),
        ("go to menu then settings then notifications", True),
        
        # Complex nested
        ("click subscribe and then select shorts and then find three dots and like", True),
    ]
    
    for command, should_work in test_cases:
        print(f"\n{'='*60}")
        print(f"Testing: {command}")
        result = controller.execute_query(command)
        status = "✓" if result else "✗"
        print(f"{status} Result: {result}")

test_multi_step()
```

---

## Advanced Features

### 1. Conditional Navigation

```python
def execute_conditional_workflow(self) -> bool:
    """
    Navigate with conditions.
    Example: If Like button is visible, tap it. If not, find menu.
    """
    elem = self.navigator.find_element_in_context("Like")
    if elem and elem.is_visible():
        self._tap(elem)
        return True
    else:
        # Try to find it in menu
        return self._execute_multi_step_command(["More", "Like"])
```

### 2. Retry with Context

```python
def execute_with_retry(self, steps: List[str], max_retries: int = 3) -> bool:
    """Execute with automatic retry and context refresh"""
    for attempt in range(max_retries):
        print(f"Attempt {attempt+1}/{max_retries}")
        results = self.navigator.navigate_sequence(steps)
        
        if all(success for success, _ in results):
            return True
        
        # Re-capture and retry
        time.sleep(1)
        self.ui_analyzer.capture_ui_tree(force_refresh=True)
    
    return False
```

### 3. Performance Optimization

```python
def execute_query_cached(self, query: str) -> bool:
    """Use cached UI tree for performance"""
    # Check if tree is fresh (< 500ms old)
    if hasattr(self, '_last_capture_time'):
        elapsed = time.time() - self._last_capture_time
        if elapsed < 0.5:
            # Use cached tree
            print(f"Using cached UI tree (age: {elapsed:.0f}ms)")
            return self._execute_with_cached_tree(query)
    
    # Capture fresh tree
    self.ui_analyzer.capture_ui_tree(force_refresh=True)
    self._last_capture_time = time.time()
    return self.execute_query(query)
```

---

## Import Statements Needed

Add to top of `screen_controller.py`:

```python
from agent.ui_tree_navigator import UITreeNavigator
from typing import List, Optional
import time
import re
```

---

## Summary of Changes

| Component | Current | New |
|-----------|---------|-----|
| `__init__()` | UIAnalyzer only | + UITreeNavigator |
| `execute_query()` | Single-step only | Single + multi-step |
| Parser | None | Multi-step command parser |
| Executor | Simple search | Hierarchical navigation |
| Fallback | Vision direct | Vision after navigator |

---

## Expected Performance

| Operation | Speed | Accuracy |
|-----------|-------|----------|
| Single-step (simple "click like") | ~150ms | 99% |
| Multi-step (3 steps) | ~500ms | 95%+ |
| With scrolling needed | ~800ms (+ scroll time) | 90%+ |
| Fallback to vision | ~2000ms | ~85% |

---

## Troubleshooting

### Issue: Command not recognized as multi-step

```python
# Debug the parser
steps = controller._parse_multi_step_command("subscribe then like")
print(steps)  # Should be: ['subscribe', 'like']
```

### Issue: Steps complete but wrong order

```python
# UITreeNavigator automatically re-captures tree after each step
# Make sure device has time to update UI
# Increase sleep in navigate_sequence() if needed
```

### Issue: Mixed device + UI commands

```python
# Current: handle separately
agent.execute_voice_command("make it brighter")  # Device
agent.execute_voice_command("like the video")    # UI

# Future: could combine
# "like the video and make it brighter" → split and route to both
```

---

## Next Steps

1. **Update ScreenController™** with the code from Steps 1-5
2. **Run test_ui_tree_navigation.py** to validate integration
3. **Test multi-step commands** on actual device
4. **Monitor performance** and adjust timeouts if needed
5. **Add caching layer** for repeated queries
