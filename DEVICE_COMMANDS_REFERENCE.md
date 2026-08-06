# Device Features - Quick Reference & Examples

## Complete Command Examples

### Brightness Control

Natural voice commands for brightness adjustment:

```
Relative Increases:
  "increase brightness"           → brightness + 10
  "make it brighter"             → brightness + 10
  "brighter please"              → brightness + 10
  "brightness up"                → brightness + 10
  "brightness +10"               → brightness + 10
  "a bit brighter"               → brightness + 5-10

Relative Decreases:
  "decrease brightness"          → brightness - 10
  "make it dimmer"               → brightness - 10
  "dimmer please"                → brightness - 10
  "brightness down"              → brightness - 10
  "brightness -10"               → brightness - 10
  "too bright"                   → brightness - 20-30

Absolute Values:
  "brightness 200"               → set to 200
  "set brightness to 150"        → set to 150
  "brightness max"               → set to 255
  "brightness 0"                 → set to 0 (minimum)
  "50% brightness"               → set to ~128

Model Understanding:
  [Qwen processes] "make it a bit brighter"
  → Tier 2 LLM classifies as: DEVICE_BRIGHTNESS with increase=10
  → Gets current brightness: 100
  → Sets new brightness: min(255, 100+10) = 110
  → Response: "✅ Brightness increased to 110/255 (43%)"
```

---

### Volume Control

Complete audio control with relative and absolute adjustments:

```
Relative Increases:
  "volume up"                    → volume + 1 step
  "louder"                       → volume + 1 step
  "increase volume"              → volume + 1 step
  "volume +5"                    → volume + 5 steps
  "crank it up"                  → volume + 3 steps
  "blast it"                     → volume + 10 steps
  "make it louder"               → volume + 2 steps
  "increase sound"               → volume + 1 step

Relative Decreases:
  "volume down"                  → volume - 1 step
  "quieter"                      → volume - 1 step
  "decrease volume"              → volume - 1 step
  "volume -3"                    → volume - 3 steps
  "reduce sound"                 → volume - 1 step
  "turn down the volume"         → volume - 1 step
  "too loud"                     → volume - 3-5 steps
  "not so loud"                  → volume - 2 steps

Absolute Levels (0-15):
  "set volume to 5"              → set to 5
  "volume 10"                    → set to 10
  "volume 15"                    → set to 15
  "volume max"                   → set to 15
  "full volume"                  → set to 15
  "volume minimum"               → set to 0

Mute/Unmute:
  "mute"                         → silence device
  "mute the device"              → silence device
  "silence"                      → silence device
  "turn off sound"               → silence device
  
  "unmute"                       → restore sound
  "restore sound"                → restore sound
  "turn on sound"                → restore sound

Model Understanding:
  [User says] "too loud, turn it down a lot"
  → Tier 2 LLM classifies: DEVICE_AUDIO with decrease
  → Extracts amount: "a lot" = large decrease = -5
  → Executes: volume_decrease(5)
  → Each call sends VOLUME_DOWN keycode 5 times
  → Response: "✅ Volume decreased"
```

---

### WiFi Control

```
Enable WiFi:
  "enable wifi"                  → wifi_enable()
  "turn on the wifi"             → wifi_enable()
  "turn wifi on"                 → wifi_enable()

Disable WiFi:
  "disable wifi"                 → wifi_disable()
  "turn off the wifi"            → wifi_disable()
  "turn wifi off"                → wifi_disable()

Toggle WiFi:
  "toggle wifi"                  → wifi_toggle()
  "switch wifi"                  → wifi_toggle()

Check Status:
  "wifi status"                  → returns ON/OFF
  "is wifi on"                   → returns ON/OFF
```

---

### Bluetooth Control

```
Enable:
  "enable bluetooth"
  "turn on bluetooth"
  "bluetooth on"

Disable:
  "disable bluetooth"
  "turn off bluetooth"
  "bluetooth off"

Toggle:
  "toggle bluetooth"
  "switch bluetooth"
```

---

### Torch/Flashlight

```
Enable:
  "enable torch"
  "turn on the torch"
  "turn on flashlight"
  "enable flash"
  "light on"

Disable:
  "disable torch"
  "turn off the torch"
  "turn off flashlight"
  "disable flash"
  "light off"

Toggle:
  "toggle torch"
  "toggle flashlight"
```

---

### Camera

```
Launch Camera:
  "launch camera"
  "open camera"
  "start camera"
  "activate camera"

Launch Video:
  "record video"
  "start video camera"
  "video camera"
  "launch video camera"

Take Photo:
  "take a photo"
  "take photo"
  "capture photo"
  "take a picture"
```

---

### Airplane Mode

```
Enable:
  "enable airplane mode"
  "turn on airplane mode"
  "airplane mode on"

Disable:
  "disable airplane mode"
  "turn off airplane mode"
  "airplane mode off"

Toggle:
  "toggle airplane mode"
  "switch airplane mode"
```

---

### Location Services

```
Enable:
  "enable location"
  "turn on location"
  "enable gps"
  "turn on gps"
  "enable positioning"

Disable:
  "disable location"
  "turn off location"
  "disable gps"
  "turn off gps"

Toggle:
  "toggle location"
  "toggle gps"
```

---

### Do Not Disturb

```
Enable:
  "enable do not disturb"
  "enable dnd"
  "turn on do not disturb"
  "silent mode"

Disable:
  "disable do not disturb"
  "disable dnd"
  "turn off do not disturb"

Toggle:
  "toggle do not disturb"
  "toggle dnd"
```

---

### Battery Saver

```
Enable:
  "enable battery saver"
  "turn on battery saver"
  "battery saver on"

Disable:
  "disable battery saver"
  "turn off battery saver"

Toggle:
  "toggle battery saver"
```

---

### Mobile Data

```
Enable:
  "enable mobile data"
  "turn on mobile data"
  "enable hotspot"
  "enable data"

Disable:
  "disable mobile data"
  "turn off mobile data"
  "disable data"

Toggle:
  "toggle mobile data"
```

---

### NFC

```
Enable:
  "enable nfc"
  "turn on nfc"

Disable:
  "disable nfc"
  "turn off nfc"

Toggle:
  "toggle nfc"
```

---

### Vibration

```
Enable:
  "enable vibration"
  "turn on vibration"
  "vibration on"

Disable:
  "disable vibration"
  "turn off vibration"
  "vibration off"

Toggle:
  "toggle vibration"
```

---

### Auto-Rotate

```
Enable:
  "enable auto rotate"
  "turn on auto rotate"
  "auto rotate on"

Disable:
  "disable auto rotate"
  "turn off auto rotate"
  "auto rotate off"

Toggle:
  "toggle auto rotate"
```

---

## Device Status

```
Check Overall Status:
  "device status"                → Shows all features
  "show device status"           → Shows all features
  "device info"                  → Shows all features
  "available features"           → Lists all features
  "show available features"      → Lists all features

Example Response:
  📱 Device Status:
   ✅ WiFi
   ❌ Bluetooth
   ✅ Mobile Data
   ❌ Torch
   ✅ Location
```

---

## Architecture in Action

### Example 1: "Make it brighter"

```
┌──────────────────────────────────┐
│ User says: "make it brighter"    │
└────────────┬─────────────────────┘
             │
             ▼
┌──────────────────────────────────┐
│ Tier 1: TF-IDF Matching          │
│ Score: 0.45 (too low)            │
│ Result: Uncertain ✗              │
└────────────┬─────────────────────┘
             │
             ▼
┌──────────────────────────────────┐
│ Tier 2: Ollama LLM               │
│ Model: qwen2.5:0.5b              │
│ Input: "make it brighter"        │
│ Inference: 300-800ms             │
│ Result:                          │
│ {                                │
│   "action": "DEVICE_BRIGHTNESS",│
│   "params": {                    │
│     "type": "increase",          │
│     "amount": 10                 │
│   }                              │
│ }                                │
└────────────┬─────────────────────┘
             │
             ▼
┌──────────────────────────────────┐
│ Tier 3: Cache for Next Time      │
│ Store: "make it brighter"        │
│        → DEVICE_BRIGHTNESS +10   │
└────────────┬─────────────────────┘
             │
             ▼
┌──────────────────────────────────┐
│ Execute:                         │
│ current_brightness = 100         │
│ new = min(255, 100 + 10) = 110   │
│ set_brightness(110)              │
└────────────┬─────────────────────┘
             │
             ▼
┌──────────────────────────────────┐
│ Response:                        │
│ ✅ Brightness increased to       │
│    110/255 (43%)                 │
└──────────────────────────────────┘

Next time user says this:
→ Tier 1 recognizes it (cached)
→ Auto-execute in ~2ms
```

### Example 2: "Volume +5"

```
Input: "volume +5"
   │
   ▼
Tier 1 matches: "volume\s*(\+\d+)"
   │
   ▼
Extract: amount = +5
DeviceAudio action, increase=5
   │
   ▼
Execute:
  for i in range(5):
    adb.run(["shell", "input", "keyevent", "24"])  # VOLUME_UP
   │
   ▼
Response: ✅ Volume increased by 5 steps
```

---

## Relative vs Absolute Values

### Brightness Examples

```
Type          Input                  Result
────────────────────────────────────────────────
Relative (+)  "brighter"            current + 10
Relative (+)  "brightness +20"      current + 20
Absolute      "brightness 200"      set to 200
Absolute      "brightness max"      set to 255
Percentage    "brightness 50%"      set to 128

Current: 100
"make it brighter"     → 110
"brightness +30"       → 130
"brightness 200"       → 200
```

### Volume Examples

```
Type          Input                  Result
────────────────────────────────────────────────
Relative (+)  "louder"              current_volume + 1
Relative (+)  "volume +5"           current_volume + 5
Relative (-)  "quieter"             current_volume - 1
Relative (-)  "volume -3"           current_volume - 3
Absolute      "volume 10"           set to 10
Absolute      "volume max"          set to 15
Absolute      "volume 0"            set to 0 (mute equivalent)

Current Volume: 8
"louder"              → 9
"crank it up"         → 11
"volume +5"           → 13
"volume -2"           → 6
"volume 15"           → 15 (max)
```

---

## Learning System

### First Time Usage (LLM Processing)

```
User: "make the screen more brilliant" (unusual phrasing)
  → Tier 1: No match (0.2 score)
  → Tier 2: LLM classifies
  → 500ms processing
  → Execute
  → Cache for next time
```

### Second Time Usage (From Cache)

```
User: "make the screen more brilliant" (same phrase)
  → Tier 1: Cache hit! (0.99 score)
  → Direct execution
  → 2ms processing ✅
```

### Similar Phrases (Tier 1 Pattern Match)

```
First learned: "make it brighter"
Later:         "make the screen brighter"
  → Tier 1: Similar patterns
  → Confidence: 0.85
  → Direct execution
  → Fast response ✅
```

---

## Performance Metrics

```
Command Type              First Use    Cached    Notes
──────────────────────────────────────────────────────────
Known pattern (Tier 1)    5-10ms       2ms       Pre-loaded
New phrasing (Tier 2)     300-800ms    2ms       LLM inference
Simple device toggle      5-10ms       2ms       Quick enable/disable
Complex command           500-1500ms   2-5ms     Multiple steps
Compound (2 actions)      10-20ms      5-10ms    Sequential execution
```

---

## FAQ

**Q: Why is my first command slow?**
A: First use triggers Tier 2 LLM inference (300-800ms). Future uses are instant.

**Q: Can I use "+10" or "-10" directly?**
A: Yes! "brightness +10", "volume -5", etc. all work.

**Q: How do I make it faster?**
A: Use it twice - first time caches, second time is instant.

**Q: What if the model misunderstands?**
A: Say the command differently or use more direct phrasing. The cache learns variations.

**Q: Can I undo a command?**
A: No auto-undo, but you can reverse: "brightness 100" then "brightness 120".

**Q: Which commands use relative vs absolute?**
A: "Brighter/louder" = relative, "brightness 200/volume 10" = absolute.

**Q: What's the maximum brightness/volume?**
A: Brightness: 0-255, Volume: 0-15 (typical Android).
