# =========================
# FILE: agent/intelligent_device_controller.py
# =========================
"""
Intelligent Device Controller — Uses 3-Tier Architecture
Leverages the same LLM system as IntentEngine for device commands.

Architecture:
  TIER 1: Pattern matching in learned cache (instant)
  TIER 2: LLM natural language understanding (fast)
  TIER 3: Learning cache for future speed-up

Examples (all understood naturally):
  ✓ "increase brightness" → Set brightness to 150
  ✓ "make it brighter" → Set brightness higher
  ✓ "brightness 200" → Set brightness to 200
  ✓ "too bright" → Decrease brightness
  ✓ "turn on the wifi" → Enable WiFi
  ✓ "turn off wifi" → Disable WiFi
  ✓ "enable flashlight" → Turn on torch
  ✓ "device status" → Show all features
"""

import re
import json
from typing import Optional, Dict, Tuple
from agent.device_features import DeviceFeatureController, FeatureName
from agent.intent_engine import LLMClassifier, LearningCache


# Map device action to feature commands
DEVICE_ACTION_MAP = {
    "DEVICE_WIFI": ("wifi", ["enable", "disable", "toggle"]),
    "DEVICE_BLUETOOTH": ("bluetooth", ["enable", "disable", "toggle"]),
    "DEVICE_TORCH": ("torch", ["enable", "disable", "toggle"]),
    "DEVICE_CAMERA": ("camera", ["launch", "video", "photo"]),
    "DEVICE_BRIGHTNESS": ("screen_brightness", ["increase", "decrease", "set"]),
    "DEVICE_AUDIO": ("volume", ["increase", "decrease", "set", "mute", "unmute"]),
    "DEVICE_LOCATION": ("location", ["enable", "disable", "toggle"]),
    "DEVICE_AIRPLANE_MODE": ("airplane_mode", ["enable", "disable", "toggle"]),
    "DEVICE_VIBRATION": ("vibration", ["enable", "disable", "toggle"]),
    "DEVICE_DO_NOT_DISTURB": ("do_not_disturb", ["enable", "disable", "toggle"]),
    "DEVICE_BATTERY_SAVER": ("battery_saver", ["enable", "disable", "toggle"]),
    "DEVICE_MOBILE_DATA": ("mobile_data", ["enable", "disable", "toggle"]),
    "DEVICE_NFC": ("nfc", ["enable", "disable", "toggle"]),
    "DEVICE_AUTO_ROTATE": ("auto_rotate", ["enable", "disable", "toggle"]),
    "DEVICE_STATUS": ("status", ["show"]),
}


class IntelligentDeviceController:
    """
    Uses the same 3-tier LLM architecture as IntentEngine
    for understanding device commands naturally.
    """

    def __init__(self, device_features: DeviceFeatureController, 
                 intent_engine_llm_model: str = "openai/gpt-oss-20b") -> None:
        """
        Initialize with:
        - device_features: DeviceFeatureController instance
        - intent_engine_llm_model: The LLM model to use (must match IntentEngine)
        """
        self.device = device_features
        self.llm = LLMClassifier(model=intent_engine_llm_model)
        self.cache = LearningCache(path="learned_device_actions.json")

    def execute_command(self, query: str) -> str:
        """
        Execute device command using 3-tier system:
        1. Check learned cache (instant)
        2. Use LLM for understanding (if needed)
        3. Store result for future speed-up
        
        Returns: Status message (✅ or ❌)
        """
        query_normalized = query.strip().lower()

        # ========== TIER 1: Check Cache (instant) ==========
        cached = self.cache.lookup(query_normalized)
        if cached:
            return self._execute_cached(cached, query)

        # ========== TIER 2: Use LLM for Understanding ==========
        action_result = self._understand_via_llm(query)
        if not action_result:
            return "❌ Device command not understood (LLM unavailable)"

        action, device_action, params = action_result

        # ========== TIER 3: Store in Cache ==========
        self.cache.store(
            phrase=query_normalized,
            action=f"DEVICE_{action}",
            params=params,
            source="llm",
            examples=[query]
        )

        # Execute the command
        return self._execute_device_action(action, device_action, params, query)

    def _understand_via_llm(self, query: str) -> Optional[Tuple[str, str, Dict]]:
        """
        Use LLM to understand device command naturally.
        Returns: (action_type, feature_name, params) or None
        """
        if not self.llm.available:
            return None

        try:
            # Use LLM classifier to understand the command
            llm_result = self.llm.classify(query)
            if not llm_result:
                return None

            action = llm_result.get("action", "")

            # Map LLM action to device feature
            if not action.startswith("DEVICE_"):
                return None

            if action not in DEVICE_ACTION_MAP:
                return None

            feature_name, _ = DEVICE_ACTION_MAP[action]
            
            # Extract action type (enable/disable/toggle/increase/decrease/set/show/launch)
            action_type = self._extract_action_type(query, action, llm_result)
            
            # Extract parameters if needed
            params = {
                "action_type": action_type,
                "query": query,
                "amount": self._extract_numeric_param(query, feature_name),
            }

            return (action_type, feature_name, params)

        except Exception as e:
            print(f"  ⚠️ LLM understanding failed: {e}")
            return None

    def _extract_action_type(self, query: str, action: str, llm_result: Dict) -> str:
        """Determine the type of action (enable/disable/toggle/etc)"""
        q = query.lower()

        # Check query for action keywords
        if any(w in q for w in ["enable", "turn on", "switch on", "activate", "start"]):
            return "enable"
        if any(w in q for w in ["disable", "turn off", "switch off", "deactivate"]):
            return "disable"
        if any(w in q for w in ["toggle", "switch", "flip"]):
            return "toggle"
        if any(w in q for w in ["increase", "brighter", "louder", "more", "raise", "higher", "crank", "blast", "boost", "pump"]):
            return "increase"
        if any(w in q for w in ["decrease", "dimmer", "quieter", "less", "lower", "reduce", "dim"]):
            return "decrease"
        if any(w in q for w in ["set", "to"]) and ("brightness" in q or "volume" in q or "level" in q):
            return "set"
        if any(w in q for w in ["mute", "silence"]):
            return "mute"
        if any(w in q for w in ["unmute", "restore", "unsilence"]):
            return "unmute"
        if "camera" in q or "photo" in q or "picture" in q or "video" in q:
            return "launch"
        if any(w in q for w in ["show", "list", "status", "available"]):
            return "show"

        # Default to enable for most device features
        return "enable"

    def _extract_numeric_param(self, query: str, feature_name: str) -> Optional[int]:
        """Extract numeric parameters like 'brightness 200' or 'set to 150'
        Also handles relative values like '+10', '-10', 'more', 'less'
        """
        q = query.lower()
        
        # Check for relative keywords FIRST
        if any(w in q for w in ["more", "higher", "increase", "brighter", "louder", "boost", "crank"]):
            return 10  # Relative +10
        if any(w in q for w in ["less", "lower", "decrease", "dimmer", "quieter", "reduce"]):
            return -10  # Relative -10
        
        # Look for explicit +/- values
        match = re.search(r'([+-]\d+)', query)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                pass
        
        # Look for absolute values like "brightness 200", "to 150", "100"
        patterns = [
            r'(?:brightness|volume|level|to)?\s*(\d+)\s*(?:%|percent)?',
            r'(\d+)\s*(?:%|percent)?',
        ]

        for pattern in patterns:
            match = re.search(pattern, query)
            if match:
                try:
                    value = int(match.group(1))
                    # Clamp brightness to 0-255
                    if feature_name == "screen_brightness":
                        value = max(0, min(255, value))
                    # Clamp volume to 0-15
                    elif feature_name == "volume":
                        value = max(0, min(15, value))
                    return value
                except (ValueError, IndexError):
                    pass

        return None

    def _execute_cached(self, cached: Dict, query: str) -> str:
        """Execute a cached device command"""
        action = cached.get("action", "").replace("DEVICE_", "").lower()
        params = cached.get("params", {})

        if action in DEVICE_ACTION_MAP:
            _, feature_name = DEVICE_ACTION_MAP[f"DEVICE_{action.upper()}"]
            action_type = params.get("action_type", "enable")
            amount = params.get("amount")
            return self._execute_device_action(action_type, feature_name, params, query)

        return "❌ Cached command failed"

    def _execute_device_action(self, action_type: str, feature_name: str, 
                              params: Dict, query: str) -> str:
        """Execute the actual device action"""
        try:
            if action_type == "enable":
                success = self.device.feature_enable(feature_name)  # type: ignore
                return f"✅ {feature_name.replace('_', ' ').title()} enabled" if success \
                       else f"❌ Failed to enable {feature_name}"

            elif action_type == "disable":
                success = self.device.feature_disable(feature_name)  # type: ignore
                return f"✅ {feature_name.replace('_', ' ').title()} disabled" if success \
                       else f"❌ Failed to disable {feature_name}"

            elif action_type == "toggle":
                success = self.device.feature_toggle(feature_name)  # type: ignore
                return f"✅ {feature_name.replace('_', ' ').title()} toggled" if success \
                       else f"❌ Failed to toggle {feature_name}"

            elif action_type == "increase":
                if feature_name == "screen_brightness":
                    current = self.device.screen_brightness_get() or 128
                    amount = params.get("amount") or 10
                    # If amount is relative (+10, -10), use it directly
                    # Otherwise it's absolute, so set it directly
                    if amount > 0 and amount < 50:  # Looks like relative
                        new_value = min(255, current + amount)
                    else:
                        new_value = min(255, current + 10)
                    success = self.device.screen_brightness_set(new_value)
                    percentage = int((new_value / 255) * 100)
                    return f"✅ Brightness increased to {new_value}/255 ({percentage}%)" if success \
                           else "❌ Failed to increase brightness"
                
                elif feature_name == "volume":
                    amount = params.get("amount") or 1
                    if amount > 0 and amount < 50:  # Relative
                        success = self.device.volume_increase(amount)
                    else:
                        success = self.device.volume_increase(1)
                    return f"✅ Volume increased" if success \
                           else "❌ Failed to increase volume"
                return f"❌ Cannot increase {feature_name}"

            elif action_type == "decrease":
                if feature_name == "screen_brightness":
                    current = self.device.screen_brightness_get() or 128
                    amount = params.get("amount") or 10
                    # Handle negative (relative -10) or positive (absolute 100)
                    if amount < 0:  # Already negative like -10
                        new_value = max(0, current + amount)  # current + (-10)
                    elif amount < 50:  # Small positive, treat as relative
                        new_value = max(0, current - amount)
                    else:  # Large number, treat as absolute
                        new_value = max(0, amount)
                    success = self.device.screen_brightness_set(new_value)
                    percentage = int((new_value / 255) * 100)
                    return f"✅ Brightness decreased to {new_value}/255 ({percentage}%)" if success \
                           else "❌ Failed to decrease brightness"
                
                elif feature_name == "volume":
                    amount = params.get("amount") or 1
                    if isinstance(amount, int) and amount != 0:
                        success = self.device.volume_decrease(abs(amount))
                    else:
                        success = self.device.volume_decrease(1)
                    return f"✅ Volume decreased" if success \
                           else "❌ Failed to decrease volume"
                return f"❌ Cannot decrease {feature_name}"

            elif action_type == "set":
                amount = params.get("amount")
                if amount is not None and feature_name == "screen_brightness":
                    success = self.device.screen_brightness_set(amount)
                    percentage = int((amount / 255) * 100)
                    return f"✅ Brightness set to {amount}/255 ({percentage}%)" if success \
                           else "❌ Failed to set brightness"
                elif amount is not None and feature_name == "volume":
                    success = self.device.volume_set(amount)
                    return f"✅ Volume set to {amount}" if success \
                           else "❌ Failed to set volume"
                return "❌ Nothing to set"

            elif action_type == "mute":
                if feature_name == "volume":
                    success = self.device.volume_mute()
                    return "✅ Device muted" if success else "❌ Failed to mute"
                return "❌ Cannot mute this feature"

            elif action_type == "unmute":
                if feature_name == "volume":
                    success = self.device.volume_unmute()
                    return "✅ Device unmuted" if success else "❌ Failed to unmute"
                return "❌ Cannot unmute this feature"

            elif action_type == "launch":
                if feature_name == "camera":
                    success = self.device.camera_launch()
                    return "✅ Camera launched" if success else "❌ Failed to launch camera"
                return f"❌ Cannot launch {feature_name}"

            elif action_type == "show":
                if feature_name == "status":
                    return self.device.get_status_string()
                return "❌ Cannot show status for this feature"

            else:
                return f"❌ Unknown action type: {action_type}"

        except Exception as e:
            return f"❌ Execution error: {e}"

    def get_learned_count(self) -> int:
        """Get number of learned device commands"""
        return self.cache.count


# ========================================================
# Quick Test
# ========================================================

if __name__ == "__main__":
    from agent.adb import AdbClient

    try:
        print("\n" + "="*60)
        print("INTELLIGENT DEVICE CONTROLLER TEST")
        print("="*60 + "\n")

        adb = AdbClient()
        device = DeviceFeatureController(adb)
        controller = IntelligentDeviceController(device)

        test_commands = [
            "increase brightness",
            "make it brighter",
            "decrease the brightness please",
            "set brightness to 200",
            "brightness 150",
            "turn on the wifi",
            "enable wifi",
            "disable wifi",
            "turn off the wifi",
            "enable flashlight",
            "turn on torch",
            "toggle do not disturb",
            "device status",
            "available features",
        ]

        for cmd in test_commands:
            print(f"> {cmd}")
            result = controller.execute_command(cmd)
            print(f"  {result}\n")

        print("="*60)
        print(f"✅ Learned {controller.get_learned_count()} commands")
        print("="*60 + "\n")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
