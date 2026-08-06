# =========================
# FILE: DEVICE_FEATURES_GUIDE.md
# =========================

# Android Device Features Control - Setup & Usage Guide

This guide explains how to use the new device features control system without disrupting your existing code.

## Files Created

1. **agent/device_features.py**
   - Main device control module
   - ~300+ methods for controlling Android device features
   - Works independently - no changes to existing files

2. **agent/device_command_mapper.py**
   - Maps natural language voice commands to device features
   - Includes command parsing and execution
   - Can integrate with your voice system

## Supported Features

### Connectivity
- WiFi (enable/disable/status/toggle)
- Bluetooth (enable/disable/status/toggle)
- Mobile Data (enable/disable)
- Airplane Mode (enable/disable/toggle)
- NFC (enable/disable)

### Hardware Control
- **Torch/Flashlight** (enable/disable)
- **Camera** (launch/launch video/take photo)

### Display & Sound
- Auto-rotate (enable/disable/toggle)
- Screen Brightness (set 0-255)
- Vibration (enable/disable)
- Haptic Feedback (enable/disable)

### Location & Privacy
- Location Services (enable/disable/toggle)
- GPS (enable/disable/toggle)

### System Settings
- Do Not Disturb (enable/disable)
- Battery Saver (enable/disable)
- USB Debugging (enable/disable)
- Screen On/Off/Lock
- Screen Timeout (set duration)

### Accessibility
- Text-to-Speech (enable/disable)
- Screen Reader (enable/disable)

---

## Quick Start - 3 Usage Scenarios

### Option 1: Standalone Usage (No Code Changes)

```python
from agent.adb import AdbClient
from agent.device_features import DeviceFeatureController

# Initialize
adb = AdbClient()
device = DeviceFeatureController(adb)

# Use directly
device.wifi_enable()
device.torch_disable()
device.camera_launch()
device.screen_brightness_set(150)
device.do_not_disturb_enable()

# Get status
status = device.get_status_string()
print(status)
```

### Option 2: Using Command Mapper (Natural Language)

```python
from agent.adb import AdbClient
from agent.device_features import DeviceFeatureController
from agent.device_command_mapper import DeviceCommandMapper

# Initialize
adb = AdbClient()
device = DeviceFeatureController(adb)
mapper = DeviceCommandMapper(device)

# Execute voice commands naturally
result = mapper.execute_device_command("enable wifi")
print(result)  # ✅ WiFi enabled

result = mapper.execute_device_command("turn on the torch")
print(result)  # ✅ Torch enabled

result = mapper.execute_device_command("set brightness to 100")
print(result)  # ✅ Brightness set to 100

result = mapper.execute_device_command("device status")
print(result)  # Outputs device status
```

### Option 3: Integration with Existing Voice System (OPTIONAL)

To integrate with your existing controller.py, add this to handle device commands:

**In agent/controller.py (add to run_cli or handle_command):**

```python
# Add import at top
from agent.device_features import DeviceFeatureController
from agent.device_command_mapper import DeviceCommandMapper

# In run_cli() or your command handler:
device_features = DeviceFeatureController(adb)
device_mapper = DeviceCommandMapper(device_features)

# In your command processing loop:
if query.lower().startswith(("enable ", "disable ", "toggle ", "turn ", "set brightness")):
    try:
        result = device_mapper.execute_device_command(query)
        print(result)
        continue
    except Exception as e:
        print(f"Device command failed: {e}")
```

---

## Example Voice Commands

```
# Connectivity
"enable wifi"
"turn on bluetooth"
"disable airplane mode"
"toggle NFC"

# Hardware
"turn on the torch"
"enable flashlight"
"launch camera"
"take a photo"

# Display
"enable auto-rotate"
"set brightness to 150"

# System
"enable do not disturb"
"turn on battery saver"
"enable location"
"disable GPS"

# Status
"device status"
"show available features"
"get wifi status"
```

---

## Method Reference

### Basic Operations

```python
# Enable/Disable
device.wifi_enable()
device.bluetooth_disable()
device.torch_toggle()

# Get Status
status = device.wifi_status()           # Returns: True/False/None
features = device.get_all_statuses()    # Returns: Dict of all features
string = device.get_status_string()     # Returns: Human-readable status

# Batch Operations
results = device.enable_multiple(["wifi", "bluetooth", "torch"])
results = device.disable_multiple(["location", "gps"])
```

### Specific Features

```python
# WiFi
device.wifi_enable()
device.wifi_disable()
is_on = device.wifi_status()

# Bluetooth
device.bluetooth_enable()
device.bluetooth_disable()  
is_on = device.bluetooth_status()

# Torch/Flashlight
device.torch_enable()
device.torch_disable()

# Camera
device.camera_launch()           # Launch still camera
device.camera_launch_video()     # Launch video camera
device.camera_take_photo()       # Trigger photo (if camera open)

# Screen Brightness
device.screen_brightness_set(200)  # 0-255

# Screen Timeout
device.screen_timeout_set(30)      # 30 seconds

# All Others
device.<feature>_enable()
device.<feature>_disable()
device.<feature>_status()        # (if available)
```

---

## Integration Checklist

If you want to integrate with your voice system:

- [ ] Import DeviceFeatureController in your main handler
- [ ] Initialize it with your ADB client
- [ ] Import DeviceCommandMapper for natural language support
- [ ] Add device command detection to your command loop
- [ ] Test with voice commands

**Remember:** You don't need to change any existing files unless you want to integrate this. The device features work completely independently!

---

## Architecture Notes

### Why Separate Files?

1. **No Disruption**: Existing code completely unaffected
2. **Modularity**: Device features are self-contained
3. **Clean Integration**: Easy to add when ready
4. **Reusability**: Can use in other projects

### How It Works

```
Voice Command
    ↓
DeviceCommandMapper.parse_device_command()
    ↓
DeviceCommandMapper.normalize_feature_name()
    ↓
DeviceFeatureController.<feature>_<action>()
    ↓
ADB Command Execution
```

### ADB Methods Used

- `svc wifi/bluetooth/nfc/data` - Quick enable/disable
- `settings put` - System settings
- `am start` - Launch apps/intents
- `input keyevent` - Send key codes
- `dumpsys` - Get device status

All commands are wrapped with try/except for safety and graceful degradation.

---

## Testing

### Test Individual Features

```bash
# Quick test
python -c "
from agent.adb import AdbClient
from agent.device_features import DeviceFeatureController

adb = AdbClient()
device = DeviceFeatureController(adb)
device.print_available_features()
"
```

### Test Command Mapper

```bash
python agent/device_command_mapper.py
```

This will test several common commands and show results.

---

## Troubleshooting

### Feature Not Working?

1. **Check device connectivity**: `adb devices`
2. **Verify ADB permissions**: Some features need specific Android version
3. **Check device logs**: `adb logcat | grep -i wifi` (or your feature)
4. **Try manual fallback**: Some features have built-in fallbacks
5. **Check Android version**: Some settings vary by Android version

### Common Issues

| Issue | Solution |
|-------|----------|
| "Feature not available" | Feature may require Android 6.0+ |
| Permission denied | May need `adb shell su` on rooted devices |
| Torch not working | Try camera flash app or system-specific intent |
| Settings not persisting | Some features reset on reboot |
| Status always None | Device may not support status query |

---

## Future Enhancements

Possible additions:
- [ ] Headphone/speaker toggle
- [ ] Ambient display toggle
- [ ] One-handed mode
- [ ] Blue light filter
- [ ] Animation speed settings
- [ ] Voice wake-unlock settings
- [ ] Emergency SOS
- [ ] Screenshot capture
- [ ] Screen recording
- [ ] Developer options toggles
- [ ] Gesture controls

---

## API Reference

### DeviceFeatureController

**Constructor:**
```python
DeviceFeatureController(adb: AdbClient)
```

**Generic Methods:**
```python
feature_enable(feature: FeatureName) -> bool
feature_disable(feature: FeatureName) -> bool
feature_toggle(feature: FeatureName) -> bool
feature_status(feature: FeatureName) -> Optional[bool]
enable_multiple(features: list[FeatureName]) -> Dict[FeatureName, bool]
disable_multiple(features: list[FeatureName]) -> Dict[FeatureName, bool]
get_all_statuses() -> Dict[FeatureName, Optional[bool]]
get_status_string() -> str
print_available_features() -> None
```

### DeviceCommandMapper

**Constructor:**
```python
DeviceCommandMapper(device_controller: DeviceFeatureController)
```

**Methods:**
```python
parse_device_command(query: str) -> Optional[Tuple[str, FeatureName, Optional[str]]]
normalize_feature_name(feature_str: str) -> Optional[FeatureName]
execute_device_command(query: str) -> str
get_example_commands() -> str
```

---

## License & Support

These files are part of your Tablet Voice Agent project.
No external dependencies - uses only Python stdlib and your existing ADB client.

Questions? Check the code comments or test with individual methods.
