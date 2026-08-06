# =========================
# FILE: agent/device_features.py
# =========================
"""
Android Device Features Control
Controls WiFi, Bluetooth, torch, camera, and other device settings
(similar to Siri's device control capabilities)

Actions supported:
  - FEATURE_ENABLE / FEATURE_DISABLE
  - FEATURE_TOGGLE
  - FEATURE_GET_STATUS

Features supported:
  - wifi, bluetooth, torch, camera, airplane_mode, do_not_disturb
  - screen_brightness, auto_rotate, location, mobile_data, nfc
  - battery_saver, vibration, haptic_feedback, bluetooth_audio
"""

from typing import Optional, Dict, Literal, Tuple
from agent.adb import AdbClient


FeatureName = Literal[
    # Connectivity
    "wifi",
    "bluetooth", 
    "mobile_data",
    "nfc",
    "airplane_mode",
    # Camera & Torch
    "torch",
    "camera",
    # Display & Sound
    "screen_brightness",
    "auto_rotate",
    "vibration",
    "haptic_feedback",
    # Location & Privacy
    "location",
    "gps",
    # Battery & Performance
    "battery_saver",
    "bluetooth_audio",
    # System Settings
    "do_not_disturb",
    "usb_debugging",
    # Screen Control
    "screen_on_off",
    "screen_timeout",
    # Accessibility
    "text_to_speech",
    "screen_reader",
]


class DeviceFeatureController:
    """Controls Android device features via ADB."""

    def __init__(self, adb: AdbClient) -> None:
        self.adb = adb

    # ========================================================
    # CONNECTIVITY FEATURES
    # ========================================================

    def wifi_enable(self) -> bool:
        """Enable WiFi."""
        try:
            self.adb.run(["shell", "svc", "wifi", "enable"])
            return True
        except Exception as e:
            print(f"❌ WiFi enable failed: {e}")
            return False

    def wifi_disable(self) -> bool:
        """Disable WiFi."""
        try:
            self.adb.run(["shell", "svc", "wifi", "disable"])
            return True
        except Exception as e:
            print(f"❌ WiFi disable failed: {e}")
            return False

    def wifi_status(self) -> bool:
        """Get WiFi status (True = enabled, False = disabled)."""
        try:
            output = self.adb.run(["shell", "dumpsys", "connectivity"])
            return "mWifiConnectivityManager" in output
        except Exception:
            return False

    def bluetooth_enable(self) -> bool:
        """Enable Bluetooth."""
        try:
            self.adb.run(["shell", "cmd", "bluetooth_manager", "enable"])
            return True
        except Exception:
            try:
                # Fallback: use settings put
                self.adb.run([
                    "shell", "settings", "put", "secure",
                    "bluetooth_on", "1"
                ])
                return True
            except Exception as e:
                print(f"❌ Bluetooth enable failed: {e}")
                return False

    def bluetooth_disable(self) -> bool:
        """Disable Bluetooth."""
        try:
            self.adb.run(["shell", "cmd", "bluetooth_manager", "disable"])
            return True
        except Exception:
            try:
                # Fallback: use settings put
                self.adb.run([
                    "shell", "settings", "put", "secure",
                    "bluetooth_on", "0"
                ])
                return True
            except Exception as e:
                print(f"❌ Bluetooth disable failed: {e}")
                return False

    def bluetooth_status(self) -> bool:
        """Get Bluetooth status."""
        try:
            # bluetooth_on lives in the GLOBAL namespace on modern Android
            output = self.adb.run(["shell", "settings", "get", "global", "bluetooth_on"])
            if output.strip() == "1":
                return True
            # Fallback to the legacy secure namespace
            output = self.adb.run(["shell", "settings", "get", "secure", "bluetooth_on"])
            return output.strip() == "1"
        except Exception:
            return False

    def mobile_data_enable(self) -> bool:
        """Enable mobile data."""
        try:
            self.adb.run(["shell", "svc", "data", "enable"])
            return True
        except Exception as e:
            print(f"❌ Mobile data enable failed: {e}")
            return False

    def mobile_data_disable(self) -> bool:
        """Disable mobile data."""
        try:
            self.adb.run(["shell", "svc", "data", "disable"])
            return True
        except Exception as e:
            print(f"❌ Mobile data disable failed: {e}")
            return False

    def nfc_enable(self) -> bool:
        """Enable NFC."""
        try:
            self.adb.run(["shell", "svc", "nfc", "enable"])
            return True
        except Exception as e:
            print(f"❌ NFC enable failed: {e}")
            return False

    def nfc_disable(self) -> bool:
        """Disable NFC."""
        try:
            self.adb.run(["shell", "svc", "nfc", "disable"])
            return True
        except Exception as e:
            print(f"❌ NFC disable failed: {e}")
            return False

    def airplane_mode_enable(self) -> bool:
        """Enable airplane mode."""
        try:
            self.adb.run([
                "shell", "settings", "put", "global",
                "airplane_mode_on", "1"
            ])
            # Also trigger airplane mode broadcast
            self.adb.run([
                "shell", "am", "broadcast", "-a", 
                "android.intent.action.AIRPLANE_MODE",
                "--ez", "state", "true"
            ])
            return True
        except Exception as e:
            print(f"❌ Airplane mode enable failed: {e}")
            return False

    def airplane_mode_disable(self) -> bool:
        """Disable airplane mode."""
        try:
            self.adb.run([
                "shell", "settings", "put", "global",
                "airplane_mode_on", "0"
            ])
            self.adb.run([
                "shell", "am", "broadcast", "-a",
                "android.intent.action.AIRPLANE_MODE",
                "--ez", "state", "false"
            ])
            return True
        except Exception as e:
            print(f"❌ Airplane mode disable failed: {e}")
            return False

    # ========================================================
    # TORCH (FLASHLIGHT) CONTROL
    # ========================================================

    def torch_enable(self) -> bool:
        """Enable torch/flashlight."""
        try:
            # Try using service command (Android 5.0+)
            self.adb.run(["shell", "svc", "torch", "enable"])
            return True
        except Exception:
            try:
                # Fallback: open flashlight app or use intent
                self.adb.run([
                    "shell", "am", "start", "-a",
                    "android.intent.action.MAIN", "-n",
                    "com.android.systemui/.usb.UsbDebuggingActivity"
                ])
                # Better fallback: use accessibility or torch intent
                self.adb.run([
                    "shell", "am", "broadcast", "-a",
                    "com.gemini.controlcenter.TORCH_ON"
                ])
                return True
            except Exception as e:
                print(f"❌ Torch enable failed: {e}")
                return False

    def torch_disable(self) -> bool:
        """Disable torch/flashlight."""
        try:
            self.adb.run(["shell", "svc", "torch", "disable"])
            return True
        except Exception:
            try:
                self.adb.run([
                    "shell", "am", "broadcast", "-a",
                    "com.gemini.controlcenter.TORCH_OFF"
                ])
                return True
            except Exception as e:
                print(f"❌ Torch disable failed: {e}")
                return False

    # ========================================================
    # CAMERA CONTROL
    # ========================================================

    def camera_launch(self) -> bool:
        """Launch camera app."""
        try:
            self.adb.run([
                "shell", "am", "start", "-a",
                "android.media.action.STILL_IMAGE_CAMERA"
            ])
            return True
        except Exception as e:
            print(f"❌ Camera launch failed: {e}")
            return False

    def camera_launch_video(self) -> bool:
        """Launch video camera."""
        try:
            self.adb.run([
                "shell", "am", "start", "-a",
                "android.media.action.VIDEO_CAMERA"
            ])
            return True
        except Exception as e:
            print(f"❌ Video camera launch failed: {e}")
            return False

    def camera_take_photo(self) -> bool:
        """Trigger photo capture (if camera is open)."""
        try:
            # Send keycode for camera button
            self.adb.run(["shell", "input", "keyevent", "27"])
            return True
        except Exception as e:
            print(f"❌ Camera photo trigger failed: {e}")
            return False

    # ========================================================
    # DISPLAY & SOUND FEATURES
    # ========================================================

    def auto_rotate_enable(self) -> bool:
        """Enable auto-rotate."""
        try:
            self.adb.run([
                "shell", "settings", "put", "system",
                "accelerometer_rotation", "1"
            ])
            return True
        except Exception as e:
            print(f"❌ Auto-rotate enable failed: {e}")
            return False

    def auto_rotate_disable(self) -> bool:
        """Disable auto-rotate."""
        try:
            self.adb.run([
                "shell", "settings", "put", "system",
                "accelerometer_rotation", "0"
            ])
            return True
        except Exception as e:
            print(f"❌ Auto-rotate disable failed: {e}")
            return False

    def screen_brightness_set(self, brightness: int) -> bool:
        """Set screen brightness (0-255)."""
        try:
            brightness = max(0, min(255, brightness))
            self.adb.run([
                "shell", "settings", "put", "system",
                "screen_brightness", str(brightness)
            ])
            return True
        except Exception as e:
            print(f"❌ Screen brightness set failed: {e}")
            return False

    def screen_brightness_get(self) -> Optional[int]:
        """Get current screen brightness (0-255)."""
        try:
            output = self.adb.run(["shell", "settings", "get", "system", "screen_brightness"]).strip()
            return int(output)
        except Exception:
            return None

    def screen_brightness_increase(self, amount: int = 10) -> bool:
        """Increase brightness by amount (default 10)."""
        try:
            current = self.screen_brightness_get() or 100
            new_brightness = min(255, current + amount)
            return self.screen_brightness_set(new_brightness)
        except Exception as e:
            print(f"❌ Brightness increase failed: {e}")
            return False

    def screen_brightness_decrease(self, amount: int = 10) -> bool:
        """Decrease brightness by amount (default 10)."""
        try:
            current = self.screen_brightness_get() or 100
            new_brightness = max(0, current - amount)
            return self.screen_brightness_set(new_brightness)
        except Exception as e:
            print(f"❌ Brightness decrease failed: {e}")
            return False

    # ========================================================
    # AUDIO & VOLUME CONTROL
    # ========================================================

    def volume_max_index(self, stream: str = "music") -> int:
        """Max media volume index (Samsung tablets commonly use 15)."""
        cached = getattr(self, "_volume_max_index", None)
        if isinstance(cached, int) and cached > 0:
            return cached
        # Probe by reading current device-specific keys; default 15.
        max_idx = 15
        try:
            for key in ("volume_music_speaker", "volume_music"):
                raw = self.adb.run(["shell", "settings", "get", "system", key]).strip()
                if raw.isdigit() and int(raw) > max_idx:
                    max_idx = int(raw)
        except Exception:
            pass
        self._volume_max_index = max_idx
        return max_idx

    def volume_get(self, stream: str = "music") -> Optional[int]:
        """Get media volume index (prefer speaker stream on Samsung)."""
        try:
            for key in ("volume_music_speaker", "volume_music"):
                output = self.adb.run(["shell", "settings", "get", "system", key]).strip()
                if output.isdigit():
                    return int(output)
            return None
        except Exception:
            return None

    def volume_set(self, level: int, stream: str = "music", as_percent: bool = False) -> bool:
        """
        Set media volume.
        level: stream index 0..max, OR 0..100 percent when as_percent=True.
        """
        try:
            max_idx = self.volume_max_index(stream)
            if as_percent or level > max_idx:
                pct = max(0, min(100, int(level)))
                level = int(round((pct / 100.0) * max_idx))
            level = max(0, min(max_idx, int(level)))
            # NOTE: --set is required; bare trailing int is ignored by media_session.
            self.adb.run([
                "shell", "cmd", "media_session", "volume",
                "--show", "--stream", "3", "--set", str(level),
            ])
            return True
        except Exception:
            try:
                current = self.volume_get() or 0
                max_idx = self.volume_max_index()
                target = max(0, min(max_idx, int(level)))
                if target < current:
                    for _ in range(current - target):
                        self.adb.run(["shell", "input", "keyevent", "25"])
                else:
                    for _ in range(target - current):
                        self.adb.run(["shell", "input", "keyevent", "24"])
                return True
            except Exception as ex:
                print(f"❌ Volume set failed: {ex}")
                return False

    def volume_set_percent(self, percent: int) -> bool:
        """Set media volume from a 0–100 percentage."""
        return self.volume_set(percent, as_percent=True)

    def volume_increase(self, amount: int = 1) -> bool:
        """Increase volume (use amount for steps, default 1)."""
        try:
            # Use volume_up keycode multiple times
            for _ in range(min(amount, 15)):
                self.adb.run(["shell", "input", "keyevent", "24"])  # KEYCODE_VOLUME_UP
            return True
        except Exception as e:
            print(f"❌ Volume increase failed: {e}")
            return False

    def volume_decrease(self, amount: int = 1) -> bool:
        """Decrease volume (use amount for steps, default 1)."""
        try:
            # Use volume_down keycode multiple times
            for _ in range(min(amount, 15)):
                self.adb.run(["shell", "input", "keyevent", "25"])  # KEYCODE_VOLUME_DOWN
            return True
        except Exception as e:
            print(f"❌ Volume decrease failed: {e}")
            return False

    def volume_mute(self) -> bool:
        """Mute device (set ringer to silent)."""
        try:
            # 'mode_ringer' is the valid global setting (0=silent,1=vibrate,2=normal)
            self.adb.run([
                "shell", "settings", "put", "global",
                "mode_ringer", "0"
            ])
            # Also send the mute keyevent for the media stream
            self.adb.run(["shell", "input", "keyevent", "164"])  # KEYCODE_VOLUME_MUTE
            return True
        except Exception as e:
            print(f"❌ Mute failed: {e}")
            return False

    def volume_unmute(self) -> bool:
        """Unmute device (restore normal ringer)."""
        try:
            self.adb.run([
                "shell", "settings", "put", "global",
                "mode_ringer", "2"
            ])
            self.adb.run(["shell", "input", "keyevent", "164"])  # KEYCODE_VOLUME_MUTE
            return True
        except Exception as e:
            print(f"❌ Unmute failed: {e}")
            return False

    def vibration_enable(self) -> bool:
        """Enable vibration."""
        try:
            self.adb.run([
                "shell", "settings", "put", "system",
                "vibrate_on", "1"
            ])
            return True
        except Exception as e:
            print(f"❌ Vibration enable failed: {e}")
            return False

    def vibration_disable(self) -> bool:
        """Disable vibration."""
        try:
            self.adb.run([
                "shell", "settings", "put", "system",
                "vibrate_on", "0"
            ])
            return True
        except Exception as e:
            print(f"❌ Vibration disable failed: {e}")
            return False

    def haptic_feedback_enable(self) -> bool:
        """Enable haptic feedback."""
        try:
            self.adb.run([
                "shell", "settings", "put", "system",
                "haptic_feedback_enabled", "1"
            ])
            return True
        except Exception as e:
            print(f"❌ Haptic feedback enable failed: {e}")
            return False

    def haptic_feedback_disable(self) -> bool:
        """Disable haptic feedback."""
        try:
            self.adb.run([
                "shell", "settings", "put", "system",
                "haptic_feedback_enabled", "0"
            ])
            return True
        except Exception as e:
            print(f"❌ Haptic feedback disable failed: {e}")
            return False

    # ========================================================
    # LOCATION & PRIVACY
    # ========================================================

    def location_enable(self) -> bool:
        """Enable location services."""
        try:
            self.adb.run([
                "shell", "settings", "put", "secure",
                "location_mode", "3"
            ])
            return True
        except Exception as e:
            print(f"❌ Location enable failed: {e}")
            return False

    def location_disable(self) -> bool:
        """Disable location services."""
        try:
            self.adb.run([
                "shell", "settings", "put", "secure",
                "location_mode", "0"
            ])
            return True
        except Exception as e:
            print(f"❌ Location disable failed: {e}")
            return False

    def gps_enable(self) -> bool:
        """Enable GPS (high accuracy location)."""
        try:
            self.adb.run([
                "shell", "settings", "put", "secure",
                "location_mode", "3"
            ])
            return True
        except Exception as e:
            print(f"❌ GPS enable failed: {e}")
            return False

    def gps_disable(self) -> bool:
        """Disable GPS."""
        try:
            self.adb.run([
                "shell", "settings", "put", "secure",
                "location_mode", "0"
            ])
            return True
        except Exception as e:
            print(f"❌ GPS disable failed: {e}")
            return False

    # ========================================================
    # BATTERY & PERFORMANCE
    # ========================================================

    def battery_saver_enable(self) -> bool:
        """Enable battery saver mode."""
        try:
            self.adb.run([
                "shell", "settings", "put", "global",
                "low_power", "1"
            ])
            return True
        except Exception as e:
            print(f"❌ Battery saver enable failed: {e}")
            return False

    def battery_saver_disable(self) -> bool:
        """Disable battery saver mode."""
        try:
            self.adb.run([
                "shell", "settings", "put", "global",
                "low_power", "0"
            ])
            return True
        except Exception as e:
            print(f"❌ Battery saver disable failed: {e}")
            return False

    # ========================================================
    # SYSTEM FEATURES
    # ========================================================

    def do_not_disturb_enable(self) -> bool:
        """Enable Do Not Disturb mode."""
        try:
            # Android 6.0+
            self.adb.run([
                "shell", "settings", "put", "global",
                "zen_mode", "1"
            ])
            return True
        except Exception as e:
            print(f"❌ Do Not Disturb enable failed: {e}")
            return False

    def do_not_disturb_disable(self) -> bool:
        """Disable Do Not Disturb mode."""
        try:
            self.adb.run([
                "shell", "settings", "put", "global",
                "zen_mode", "0"
            ])
            return True
        except Exception as e:
            print(f"❌ Do Not Disturb disable failed: {e}")
            return False

    def usb_debugging_enable(self) -> bool:
        """Enable USB debugging."""
        try:
            self.adb.run([
                "shell", "settings", "put", "secure",
                "adb_enabled", "1"
            ])
            return True
        except Exception as e:
            print(f"❌ USB debugging enable failed: {e}")
            return False

    def usb_debugging_disable(self) -> bool:
        """Disable USB debugging."""
        try:
            self.adb.run([
                "shell", "settings", "put", "secure",
                "adb_enabled", "0"
            ])
            return True
        except Exception as e:
            print(f"❌ USB debugging disable failed: {e}")
            return False

    # ========================================================
    # SCREEN CONTROL
    # ========================================================

    def screen_on(self) -> bool:
        """Turn screen on."""
        try:
            self.adb.run(["shell", "input", "keyevent", "26"])
            return True
        except Exception as e:
            print(f"❌ Screen on failed: {e}")
            return False

    def screen_off(self) -> bool:
        """Turn screen off."""
        try:
            self.adb.run(["shell", "input", "keyevent", "26"])
            return True
        except Exception as e:
            print(f"❌ Screen off failed: {e}")
            return False

    def screen_lock(self) -> bool:
        """Lock the screen."""
        try:
            self.adb.run(["shell", "input", "keyevent", "26"])
            return True
        except Exception as e:
            print(f"❌ Screen lock failed: {e}")
            return False

    def screen_timeout_set(self, seconds: int) -> bool:
        """Set screen timeout (seconds)."""
        try:
            milliseconds = seconds * 1000
            self.adb.run([
                "shell", "settings", "put", "system",
                "screen_off_timeout", str(milliseconds)
            ])
            return True
        except Exception as e:
            print(f"❌ Screen timeout set failed: {e}")
            return False

    # ========================================================
    # ACCESSIBILITY
    # ========================================================

    def text_to_speech_enable(self) -> bool:
        """Enable text-to-speech."""
        try:
            self.adb.run([
                "shell", "settings", "put", "secure",
                "tts_default_synthesis_speech_rate", "100"
            ])
            return True
        except Exception as e:
            print(f"❌ Text-to-speech enable failed: {e}")
            return False

    def screen_reader_enable(self) -> bool:
        """Enable screen reader (TalkBack)."""
        try:
            self.adb.run([
                "shell", "settings", "put", "secure",
                "accessibility_enabled", "1"
            ])
            return True
        except Exception as e:
            print(f"❌ Screen reader enable failed: {e}")
            return False

    def screen_reader_disable(self) -> bool:
        """Disable screen reader."""
        try:
            self.adb.run([
                "shell", "settings", "put", "secure",
                "accessibility_enabled", "0"
            ])
            return True
        except Exception as e:
            print(f"❌ Screen reader disable failed: {e}")
            return False

    # ========================================================
    # GENERIC CONTROL INTERFACE
    # ========================================================

    def feature_enable(self, feature: FeatureName) -> bool:
        """Enable a feature by name."""
        method_name = f"{feature}_enable"
        if hasattr(self, method_name):
            return getattr(self, method_name)()
        print(f"❌ Unknown feature: {feature}")
        return False

    def feature_disable(self, feature: FeatureName) -> bool:
        """Disable a feature by name."""
        method_name = f"{feature}_disable"
        if hasattr(self, method_name):
            return getattr(self, method_name)()
        print(f"❌ Unknown feature: {feature}")
        return False

    def feature_toggle(self, feature: FeatureName) -> bool:
        """Toggle a feature (enable if off, disable if on)."""
        # For features with status methods
        if feature in ["wifi", "bluetooth", "location", "gps", "nfc"]:
            status_method = f"{feature}_status"
            if hasattr(self, status_method):
                is_enabled = getattr(self, status_method)()
                if is_enabled:
                    return self.feature_disable(feature)
                else:
                    return self.feature_enable(feature)
        
        # Default toggle: try to disable first, then enable
        return self.feature_disable(feature) or self.feature_enable(feature)

    def feature_status(self, feature: FeatureName) -> Optional[bool]:
        """Get feature status (True = enabled, False = disabled, None = unknown)."""
        status_method = f"{feature}_status"
        if hasattr(self, status_method):
            try:
                return getattr(self, status_method)()
            except Exception:
                return None
        print(f"⚠️ Status check not available for: {feature}")
        return None

    # ========================================================
    # BATCH OPERATIONS
    # ========================================================

    def enable_multiple(self, features: list[FeatureName]) -> Dict[FeatureName, bool]:
        """Enable multiple features and return results."""
        results = {}
        for feature in features:
            results[feature] = self.feature_enable(feature)
        return results

    def disable_multiple(self, features: list[FeatureName]) -> Dict[FeatureName, bool]:
        """Disable multiple features and return results."""
        results = {}
        for feature in features:
            results[feature] = self.feature_disable(feature)
        return results

    def get_all_statuses(self) -> Dict[FeatureName, Optional[bool]]:
        """Get status of all available features."""
        statuses = {}
        features: list[FeatureName] = [
            "wifi", "bluetooth", "mobile_data", "nfc", "airplane_mode",
            "location", "gps", "do_not_disturb", "battery_saver"
        ]
        for feature in features:
            statuses[feature] = self.feature_status(feature)
        return statuses

    def get_status_string(self) -> str:
        """Return human-readable status of all features."""
        statuses = self.get_all_statuses()
        lines = ["📱 Device Status:"]
        
        for feature, status in statuses.items():
            if status is True:
                icon = "✅"
            elif status is False:
                icon = "❌"
            else:
                icon = "❓"
            lines.append(f"  {icon} {feature.replace('_', ' ').title()}")
        
        return "\n".join(lines)

    def print_available_features(self) -> None:
        """Print all available features with their methods."""
        print("\n📋 Available Device Features:")
        print("   CONNECTIVITY:")
        print("     - wifi (enable/disable/status/toggle)")
        print("     - bluetooth (enable/disable/status/toggle)")
        print("     - mobile_data (enable/disable)")
        print("     - nfc (enable/disable/toggle)")
        print("     - airplane_mode (enable/disable/toggle)")
        print("\n   HARDWARE:")
        print("     - torch (enable/disable/toggle)")
        print("     - camera (launch/launch_video/take_photo)")
        print("\n   DISPLAY & SOUND:")
        print("     - auto_rotate (enable/disable/toggle)")
        print("     - screen_brightness")
        print("       • get current: screen_brightness_get() → 0-255")
        print("       • set absolute: screen_brightness_set(200)")
        print("       • increase: screen_brightness_increase(10)")
        print("       • decrease: screen_brightness_decrease(10)")
        print("     - volume")
        print("       • get current: volume_get() → 0-15")
        print("       • set absolute: volume_set(10)")
        print("       • increase: volume_increase(1-5)")
        print("       • decrease: volume_decrease(1-5)")
        print("       • mute: volume_mute()")
        print("       • unmute: volume_unmute()")
        print("     - vibration (enable/disable/toggle)")
        print("     - haptic_feedback (enable/disable/toggle)")
        print("\n   LOCATION & PRIVACY:")
        print("     - location (enable/disable/status/toggle)")
        print("     - gps (enable/disable/status/toggle)")
        print("\n   BATTERY & PERFORMANCE:")
        print("     - battery_saver (enable/disable/toggle)")
        print("\n   SYSTEM:")
        print("     - do_not_disturb (enable/disable/toggle)")
        print("     - usb_debugging (enable/disable/toggle)")
        print("     - screen_on/off/lock")
        print("     - screen_timeout (set seconds)")
        print("\n   ACCESSIBILITY:")
        print("     - text_to_speech (enable/disable)")
        print("     - screen_reader (enable/disable)")
