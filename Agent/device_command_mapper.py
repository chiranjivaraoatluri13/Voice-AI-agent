# =========================
# FILE: agent/device_command_mapper.py
# =========================
"""
Device Feature Command Mapper
Maps voice commands to device feature actions.
This helps integrate device_features.py with the main voice system.

Example voice commands:
  "enable wifi"
  "turn on bluetooth"
  "toggle airplane mode"
  "turn on the torch"
  "disable location"
  "enable do not disturb"
  "set brightness to 50"
  "take a photo"
  "launch camera"
  "device status"
  "show available features"
"""

import re
from typing import Optional, Dict, Tuple
from agent.device_features import DeviceFeatureController, FeatureName


class DeviceCommandMapper:
    """Maps natural language commands to device feature actions."""

    def __init__(self, device_controller: DeviceFeatureController) -> None:
        self.device = device_controller

    # ========================================================
    # COMMAND PARSING
    # ========================================================

    def parse_device_command(self, query: str) -> Optional[Tuple[str, FeatureName, Optional[str]]]:
        """
        Parse voice command into (action, feature, param).
        
        Actions: "enable", "disable", "toggle", "get", "set", "launch", "trigger"
        Returns: (action, feature, param) or None if not a device command
        """
        query = query.lower().strip()

        # Pattern: "enable/disable/turn on/turn off/toggle [feature]"
        # NOTE: order matters — 'set ... to N' and increase/decrease patterns are
        # placed before the generic enable/disable patterns so they win.
        for cmd, action in [
            (r"(?:set)\s+(?:the\s+)?(.+?)\s+to\s+(\d+)\s*%?\s*$", "set"),
            (r"(?:set)\s+(?:the\s+)?(volume|sound|audio|brightness|screen_brightness|screen\s+timeout|timeout)\s+(\d+)\s*%?\s*$", "set"),
            (r"(?:the\s+)?(volume|sound|audio)\s+(?:to|at)\s+(\d+)\s*%?\s*$", "set"),
            (r"(?:increase|raise|boost|turn up)\s+(?:the\s+)?(.+?)(?:\s+(?:by|to)\s+\d+)?\s*$", "increase"),
            (r"(?:decrease|lower|reduce|dim|turn down)\s+(?:the\s+)?(.+?)(?:\s+(?:by|to)\s+\d+)?\s*$", "decrease"),
            (r"(?:the\s+)?(.+?)\s+up\s*$", "increase"),
            (r"(?:the\s+)?(.+?)\s+down\s*$", "decrease"),
            (r"(?:enable|turn on)\s+(?:the\s+)?(.+?)(?:\s+(?:to|with))?\s*$", "enable"),
            (r"(?:disable|turn off)\s+(?:the\s+)?(.+?)(?:\s+(?:to|with))?\s*$", "disable"),
            (r"(?:toggle)\s+(?:the\s+)?(.+?)\s*$", "toggle"),
            (r"(?:get|check|show)\s+(?:the\s+)?(.+?)(?:\s+status)?\s*$", "get"),
            (r"(?:launch|open)\s+(?:the\s+)?(.+?)\s*$", "launch"),
            (r"(?:take|capture)\s+(?:a\s+)?(.+?)\s*$", "take"),
            (r"(?:device\s+)?status\s*$", "status"),
            (r"available\s+features\s*$", "features"),
        ]:
            match = re.match(cmd, query)
            if match:
                groups = match.groups()
                feature = groups[0].strip().replace(" ", "_") if groups and groups[0] else None
                param = groups[1] if len(groups) > 1 else None
                return (action, feature, param)

        return None

    def normalize_feature_name(self, feature_str: str) -> Optional[FeatureName]:
        """Normalize user input to feature name."""
        feature_str = feature_str.lower().replace(" ", "_")
        
        # Map aliases
        aliases = {
            "flash": "torch",
            "flashlight": "torch",
            "light": "torch",
            "brightness": "screen_brightness",
            "sound": "volume",
            "audio": "volume",
            "media_volume": "volume",
            "dnd": "do_not_disturb",
            "silent": "do_not_disturb",
            "quiet": "do_not_disturb",
            "hotspot": "mobile_data",
            "data": "mobile_data",
            "internet": "mobile_data",
            "positioning": "location",
            "silent_mode": "do_not_disturb",
            "timeout": "screen_timeout",
            "screen_lock": "screen_on_off",
            "text_to_speech": "text_to_speech",
            "tts": "text_to_speech",
            "speech": "text_to_speech",
            "screen_reader": "screen_reader",
            "talkback": "screen_reader",
            "reader": "screen_reader",
        }

        if feature_str in aliases:
            feature_str = aliases[feature_str]

        # Check if valid feature
        valid_features = [
            "wifi", "bluetooth", "mobile_data", "nfc", "airplane_mode",
            "torch", "camera", "auto_rotate", "screen_brightness", "volume",
            "vibration", "haptic_feedback", "location", "gps",
            "battery_saver", "do_not_disturb", "usb_debugging",
            "screen_on_off", "screen_timeout", "text_to_speech",
            "screen_reader"
        ]

        if feature_str in valid_features:
            return feature_str  # type: ignore

        return None

    # ========================================================
    # EXECUTE COMMANDS
    # ========================================================

    def execute_device_command(self, query: str) -> str:
        """
        Execute a device feature command and return status message.
        """
        parsed = self.parse_device_command(query)
        if not parsed:
            return "❌ Not a device command"

        action, feature_str, param = parsed

        # Handle special actions
        if action == "status":
            return self.device.get_status_string()

        if action == "features":
            self.device.print_available_features()
            return "✅ Available features listed"

        # Normalize feature name
        feature = self.normalize_feature_name(feature_str)
        if not feature:
            return f"❌ Unknown feature: {feature_str}"

        # Execute action
        if action == "enable":
            success = self.device.feature_enable(feature)
            return f"✅ {feature.replace('_', ' ').title()} enabled" if success \
                   else f"❌ Failed to enable {feature}"

        elif action == "disable":
            success = self.device.feature_disable(feature)
            return f"✅ {feature.replace('_', ' ').title()} disabled" if success \
                   else f"❌ Failed to disable {feature}"

        elif action == "toggle":
            success = self.device.feature_toggle(feature)
            return f"✅ {feature.replace('_', ' ').title()} toggled" if success \
                   else f"❌ Failed to toggle {feature}"

        elif action == "get":
            status = self.device.feature_status(feature)
            if status is True:
                return f"✅ {feature.replace('_', ' ').title()} is ON"
            elif status is False:
                return f"❌ {feature.replace('_', ' ').title()} is OFF"
            else:
                return f"❓ Status unknown for {feature}"

        elif action == "increase":
            if feature == "screen_brightness":
                success = self.device.screen_brightness_increase(40)
                return "✅ Brightness increased" if success else "❌ Failed to increase brightness"
            elif feature == "volume":
                success = self.device.volume_increase(2)
                return "✅ Volume increased" if success else "❌ Failed to increase volume"
            else:
                return f"❌ Cannot increase {feature}"

        elif action == "decrease":
            if feature == "screen_brightness":
                success = self.device.screen_brightness_decrease(40)
                return "✅ Brightness decreased" if success else "❌ Failed to decrease brightness"
            elif feature == "volume":
                success = self.device.volume_decrease(2)
                return "✅ Volume decreased" if success else "❌ Failed to decrease volume"
            else:
                return f"❌ Cannot decrease {feature}"

        elif action == "set":
            if param and feature == "screen_brightness":
                brightness = int(param)
                success = self.device.screen_brightness_set(brightness)
                return f"✅ Brightness set to {brightness}" if success \
                       else "❌ Failed to set brightness"
            elif param and feature == "volume":
                pct = int(param)
                success = self.device.volume_set_percent(pct)
                import time as _time
                _time.sleep(0.25)
                cur = self.device.volume_get()
                max_idx = self.device.volume_max_index()
                if success:
                    return f"✅ Volume set to {pct}% ({cur}/{max_idx})"
                return "❌ Failed to set volume"
            elif param and feature == "screen_timeout":
                seconds = int(param)
                success = self.device.screen_timeout_set(seconds)
                return f"✅ Screen timeout set to {seconds}s" if success \
                       else "❌ Failed to set timeout"
            else:
                return f"❌ Cannot set {feature} to {param}"

        elif action == "launch":
            if feature == "camera":
                success = self.device.camera_launch()
                return "✅ Camera launched" if success else "❌ Failed to launch camera"
            else:
                return f"❌ Cannot launch {feature}"

        elif action == "take":
            if feature == "photo" or feature == "picture":
                success = self.device.camera_take_photo()
                return "✅ Photo captured" if success else "❌ Failed to capture photo"
            else:
                return f"❌ Cannot take {feature}"

        return f"❌ Unknown action: {action}"

    # ========================================================
    # COMMON COMMAND EXAMPLES (for reference)
    # ========================================================

    def get_example_commands(self) -> str:
        """Return list of example voice commands."""
        examples = """
📌 Example Device Commands:

CONNECTIVITY:
  • "Enable WiFi" / "Turn on WiFi" / "Toggle WiFi"
  • "Turn on Bluetooth"
  • "Disable airplane mode"
  • "Enable NFC"
  • "Turn on mobile data"

HARDWARE:
  • "Enable the torch" / "Turn on flashlight"
  • "Take a photo"
  • "Launch camera"
  • "Launch video camera"

DISPLAY:
  • "Enable auto-rotate"
  • "Disable auto-rotate"
  • "Set brightness to 200"

SOUND:
  • "Enable vibration"
  • "Disable haptic feedback"

SYSTEM:
  • "Enable do not disturb"
  • "Turn on battery saver"
  • "Enable location"
  • "Disable GPS"
  • "Toggle screen on/off"

STATUS:
  • "Show device status"
  • "Show available features"
  • "Get WiFi status"
"""
        return examples


# ========================================================
# SIMPLE TEST/DEMO
# ========================================================

if __name__ == "__main__":
    from agent.adb import AdbClient

    try:
        adb = AdbClient()
        device = DeviceFeatureController(adb)
        mapper = DeviceCommandMapper(device)

        # Test commands
        test_commands = [
            "enable wifi",
            "turn on bluetooth",
            "toggle airplane mode",
            "set brightness to 100",
            "device status",
            "take a photo",
        ]

        print("Testing Device Command Mapper:\n")
        for cmd in test_commands:
            print(f"> {cmd}")
            result = mapper.execute_device_command(cmd)
            print(f"  {result}\n")

    except Exception as e:
        print(f"Error: {e}")
