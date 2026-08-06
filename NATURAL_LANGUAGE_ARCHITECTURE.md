# Natural Language Architecture - Complete Guide

## Overview

The tablet voice agent uses a **3-tier natural language understanding system** to map voice commands to device actions with high accuracy and speed. This document explains how it works and how to extend it.

---

## 3-Tier Architecture

### Tier 1: Fast Pattern Matching (TF-IDF) - ~2ms

**What it does:** Instantly matches known commands by analyzing word patterns
- Uses TF-IDF (Term Frequency-Inverse Document Frequency) scoring
- Maintains a knowledge base of 100+ pre-defined command examples
- Runs in-process, no network latency

**When it activates:** 
- Every command query FIRST goes through Tier 1
- If confidence > 0.7 → execute immediately (< 5ms latency)

**Example:**
```
Input: "increase volume"
TF-IDF Score: 0.95 (very high confidence)
Result: DEVICE_AUDIO action with increase=true
Time: ~1ms
```

---

### Tier 2: Intelligent LLM Reasoning - ~300-800ms

**What it does:** Uses Qwen LLM for true natural language understanding
- Falls back when Tier 1 confidence is low (< 0.7)
- Understands variations, typos, contextual commands
- Returns structured JSON with action + parameters

**When it activates:** 
- When Tier 1 score < 0.7
- For novel phrasings the system hasn't seen before
- For complex compound commands

**Example:**
```
Input: "make it a bit brighter" (novel phrasing)
TF-IDF Score: 0.45 (low confidence)
→ Triggers Tier 2 (LLM)
LLM Response: {"action": "DEVICE_BRIGHTNESS", "params": {"type": "increase", "amount": 10}}
Result: Brightness +10
Time: ~500ms first time, then cached
```

---

### Tier 3: Self-Learning Cache - Instant After Learning

**What it does:** Caches Tier 2 results so they become Tier 1 next time
- After LLM processes a command, it's saved to cache
- Future identical/similar phrasings skip straight to Tier 1
- Agent gets faster the more you use it

**Example Flow:**
```
First Time:  "make it brighter"        → [Tier 1 ✗] → [Tier 2 LLM] → [Cache] → Execute (500ms)
Second Time: "make it brighter"        → [Tier 1 ✓] → Execute (2ms)
Third Time:  "make the screen brighter" → [Tier 1 ✓] → Execute (2ms) [similar)
```

---

## Device Features Supported

### 1. **Brightness Control** - `DEVICE_BRIGHTNESS`

Relative and absolute brightness adjustments

```python
# Relative changes (offset from current)
"increase brightness"       → brightness_get() + 10
"brightness up"            → brightness_get() + 10
"make it brighter"         → brightness_get() + 10
"brightness +10"           → brightness_get() + 10
"brightness -5"            → brightness_get() - 5

# Absolute values
"set brightness to 200"    → brightness_set(200)
"brightness 150"           → brightness_set(150)
"brightness max"           → brightness_set(255)
"brightness 0"             → brightness_set(0)

# Degree-based
"brightness 50%"           → brightness_set(127) # 50% of 255
"brightness 100%"          → brightness_set(255)
```

**Architecture:**
```
User Input: "make it a bit brighter"
    ↓
Intent Parser (Tier 2 LLM):
  - Recognizes: "make it" + "brighter" = INCREASE action
  - Extracts amount: "a bit" = small increment = +10
    ↓
Action Mapper:
  - Device Feature: screen_brightness
  - Action Type: increase
  - Amount: 10
    ↓
Execution:
  current = device.screen_brightness_get()  # e.g., 128
  new = min(255, 128 + 10) = 138
  device.screen_brightness_set(138)
    ↓
Response: "✅ Brightness increased to 138/255 (54%)"
```

---

### 2. **Volume/Audio Control** - `DEVICE_AUDIO`

Full audio control with mute, increase, decrease, and absolute levels

```python
# Increase volume
"volume up"                  → volume_increase(1)
"louder"                     → volume_increase(1)
"increase volume"            → volume_increase(1)
"volume +5"                  → volume_increase(5)
"crank it up"               → volume_increase(3)
"blast it"                  → volume_increase(10)

# Decrease volume
"volume down"                → volume_decrease(1)
"quieter"                    → volume_decrease(1)
"decrease volume"            → volume_decrease(1)
"volume -3"                 → volume_decrease(3)
"reduce sound"              → volume_decrease(2)

# Absolute levels
"set volume to 10"          → volume_set(10)
"volume 5"                  → volume_set(5)
"full volume"               → volume_set(15)
"volume max"                → volume_set(15)

# Mute/Unmute
"mute"                      → volume_mute()
"silence device"            → volume_mute()
"unmute"                    → volume_unmute()
"restore sound"             → volume_unmute()
```

**Architecture (Same as Brightness):**
```
User Input: "too loud, turn it down"
    ↓
Intent Parser:
  - Recognizes: "too loud" + "turn it down" = DECREASE action
  - Intensity: "too" = significant = -5
    ↓
Action Mapper:
  - Device Feature: volume
  - Action Type: decrease
  - Amount: 5
    ↓
Execution:
  for i in range(5):
    device.volume_decrease(1)  # Each call sends VOLUME_DOWN keycode
```

---

### 3. **WiFi/Connectivity** - `DEVICE_WIFI`, `DEVICE_BLUETOOTH`, etc.

Simple enable/disable/toggle

```python
"enable wifi"              → DEVICE_WIFI + enable
"turn on bluetooth"        → DEVICE_BLUETOOTH + enable
"disable mobile data"      → DEVICE_MOBILE_DATA + disable
"toggle airplane mode"     → DEVICE_AIRPLANE_MODE + toggle
"turn on the torch"        → DEVICE_TORCH + enable
```

---

### 4. **Camera** - `DEVICE_CAMERA`

```python
"launch camera"            → camera.launch()
"take a photo"            → camera.take_photo()
"record video"            → camera.launch_video()
```

---

## Natural Language Understanding Examples

### Example 1: Subtle Phrasings

```
Phrasing                  → Parsed As
─────────────────────────────────────────
"turn up the sound"       → volume_increase(1)
"crank the volume"        → volume_increase(3)
"blast it"                → volume_increase(10)
"it's too loud"           → volume_decrease(3)
"barely audible"          → volume_decrease(all the way)
```

### Example 2: Natural Compound Commands

```
Input: "open spotify and play some music"
    ↓
Parser splits: ["open spotify", "play music"]
    ↓
Command 1: OPEN_APP (spotify)
Command 2: MEDIA_PLAY
    ↓
Result: 
  1. Launch Spotify
  2. Press Play
```

### Example 3: Typos & Variations

```
Acceptable inputs (all map to same action):
────────────────────────────────────────
"brighten the screan"     → screen_brightness_increase
"brighter pleeease"       → screen_brightness_increase
"mkae the screan brighter"→ screen_brightness_increase
"max out volume"          → volume_set(15)
"crank volume all the way"→ volume_set(15)
```

---

## How to Add New Device Commands

### Step 1: Add to Intent Engine ACTION_EXAMPLES

File: `agent/intent_engine.py` (around line 336)

```python
ACTION_EXAMPLES = {
    # ... existing actions ...
    
    "DEVICE_AUDIO": [
        # Natural language variations
        "increase volume", "volume up", "louder",
        "decrease volume", "volume down", "quieter",
        "set volume to 10", "mute", "unmute",
        # Including relative values
        "volume +5", "volume -3", "crank it up",
    ],
}
```

### Step 2: Add to Device Feature Controller

File: `agent/device_features.py` (around line 325)

```python
class DeviceFeatureController:
    # Add your control methods
    def my_feature_enable(self) -> bool:
        """Enable my feature."""
        try:
            self.adb.run(["shell", "cmd", "my_feature", "enable"])
            return True
        except Exception as e:
            print(f"❌ Failed: {e}")
            return False
    
    def my_feature_disable(self) -> bool:
        """Disable my feature."""
        try:
            self.adb.run(["shell", "cmd", "my_feature", "disable"])
            return True
        except Exception as e:
            print(f"❌ Failed: {e}")
            return False
```

### Step 3: Add to Intelligent Device Controller

File: `agent/intelligent_device_controller.py` (around line 33)

```python
DEVICE_ACTION_MAP = {
    # ... existing mappings ...
    "DEVICE_MY_FEATURE": ("my_feature", ["enable", "disable", "toggle"]),
}
```

### Step 4: Test

```python
from agent.adb import AdbClient
from agent.device_features import DeviceFeatureController
from agent.intelligent_device_controller import IntelligentDeviceController

adb = AdbClient()
device = DeviceFeatureController(adb)
controller = IntelligentDeviceController(device)

# Test natural language
result = controller.execute_command("enable my feature")
print(result)  # ✅ My Feature enabled
```

---

## Internal Data Flow

### Request Processing

```
┌─────────────────────────────────────────────────────────────┐
│ User Voice Input: "make it brighter"                        │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│ TIER 1: TF-IDF Pattern Matching                             │
│ - Tokenize: ["make", "brighter"]                            │
│ - Compare against ACTION_EXAMPLES                           │
│ - Score: 0.45 (low, due to "make it" phrasing)            │
└────────────────┬────────────────────────────────────────────┘
                 │
         Score < 0.7 ✗ (Uncertain)
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│ TIER 2: LLM Classifier (Ollama)                            │
│ - Model: qwen2.5:0.5b                                       │
│ - Prompt: "Classify: 'make it brighter'"                    │
│ - Response: {"action": "DEVICE_BRIGHTNESS", "amount": 10}   │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│ TIER 3: Cache + Learn                                       │
│ - Store: "make it brighter" → DEVICE_BRIGHTNESS            │
│ - Next time: Tier 1 will recognize it instantly            │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│ Execution                                                    │
│ - Feature: screen_brightness                               │
│ - Action: increase                                          │
│ - Amount: 10                                                │
│ - Get current: 128                                          │
│ - Set new: min(255, 128+10) = 138                          │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│ Response: "✅ Brightness increased to 138/255 (54%)"        │
└─────────────────────────────────────────────────────────────┘
```

---

## Performance Characteristics

| Scenario | Latency | Why |
|----------|---------|-----|
| Known command (Tier 1) | ~2ms | Pure pattern matching, in-process |
| New phrasing (Tier 2) | 300-800ms | LLM inference via Ollama |
| Previously learned | ~2ms | Cached in Tier 1 |
| Complex compound | 500-1500ms | Multiple LLM calls |

---

## Troubleshooting

### Issue: Commands not understood

**Solution:** Add more natural language examples to `ACTION_EXAMPLES`

```python
"DEVICE_BRIGHTNESS": [
    # Add your phrasing here
    "make it brighter",  # If this is missing
    "brightness up",
    # etc
]
```

### Issue: Slow response

**Reason:** Command not in Tier 1, always hitting Tier 2 LLM

**Solution:** 
1. Use the command once (Tier 2 learns it)
2. Use it again (now cached in Tier 1)
3. Second time is instant

### Issue: Wrong interpretation

**Solution:** Teach the agent via the learning interface

```
"remember that 'blast it' means maximum volume"
→ Agent learns: "blast it" → VOLUME_MAX (15)
```

---

## Architecture Summary

```
Natural Language Input
        │
        ├─────►[TF-IDF Tier 1] ───► Confidence > 0.7? ──YES──► Execute (2ms)
        │                                        │
        │                                       NO
        │                                        │
        │                                        ▼
        ├─────►[Ollama Tier 2] ───► Get action + params
        │           │
        │           └─────────────► Cache for future
        │
        └─────►[Learning Cache] ───► Updates Tier 1
                    │
                    └─────────────► Next time: instant
```

---

## Key Takeaways

1. **Tier 1 (Pattern):** Fast, for known patterns
2. **Tier 2 (LLM):** Intelligent, understands variations
3. **Tier 3 (Cache):** Learning, gets faster over time
4. **Device Features:** Fully mapped to natural language
5. **Relative Values:** Support `-10`, `+10`, `more`, `less`, etc.
6. **Extensible:** Easy to add new device features

---

## References

- [IntentEngine](agent/intent_engine.py) - 3-tier architecture code
- [DeviceFeatureController](agent/device_features.py) - Device control methods
- [IntelligentDeviceController](agent/intelligent_device_controller.py) - LLM-based device control
- [Schema](agent/schema.py) - Action definitions
