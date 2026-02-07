# =========================
# FILE: agent/device.py (COMPLETE)
# =========================
import re
import time
from typing import Tuple, Literal
from agent.adb import AdbClient

class DeviceController:
    def __init__(self, adb: AdbClient) -> None:
        self.adb = adb

    # ===========================
    # Basic Controls
    # ===========================
    
    def wake(self) -> None:
        try:
            self.adb.run(["shell", "input", "keyevent", "KEYCODE_WAKEUP"])
            time.sleep(0.12)
            self.adb.run(["shell", "input", "keyevent", "KEYCODE_MENU"])
            time.sleep(0.12)
        except Exception:
            pass

    def home(self) -> None:
        self.adb.run(["shell", "input", "keyevent", "KEYCODE_HOME"])

    def back(self) -> None:
        self.adb.run(["shell", "input", "keyevent", "KEYCODE_BACK"])

    def tap(self, x: int, y: int) -> None:
        self.adb.run(["shell", "input", "tap", str(x), str(y)])

    def type_text(self, text: str) -> None:
        self.adb.run(["shell", "input", "text", text.replace(" ", "%s")])

    def launch(self, package: str) -> None:
        self.adb.run(["shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"])
        time.sleep(0.6)

    def screen_size(self) -> Tuple[int, int]:
        out = self.adb.run(["shell", "wm", "size"])
        m = re.search(r"Physical size:\s*(\d+)x(\d+)", out)
        if not m:
            raise RuntimeError(f"Could not parse screen size from: {out}")
        return int(m.group(1)), int(m.group(2))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int) -> None:
        self.adb.run(["shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms)])
        time.sleep(0.18)

    def scroll_once(self, direction: Literal["UP", "DOWN"]) -> None:
        """Single swipe, size-agnostic."""
        w, h = self.screen_size()
        is_landscape = w > h
        x = w // 2

        if is_landscape:
            top = int(h * 0.25)
            bottom = int(h * 0.75)
            duration = 750
        else:
            top = int(h * 0.15)
            bottom = int(h * 0.85)
            duration = 650

        if direction == "DOWN":
            self.swipe(x, bottom, x, top, duration)
        else:
            self.swipe(x, top, x, bottom, duration)
    
    # ===========================
    # Volume Controls
    # ===========================
    
    def volume_up(self, times: int = 1) -> None:
        """Increase volume"""
        for _ in range(times):
            self.adb.run(["shell", "input", "keyevent", "KEYCODE_VOLUME_UP"])
            time.sleep(0.1)
    
    def volume_down(self, times: int = 1) -> None:
        """Decrease volume"""
        for _ in range(times):
            self.adb.run(["shell", "input", "keyevent", "KEYCODE_VOLUME_DOWN"])
            time.sleep(0.1)
    
    def volume_mute(self) -> None:
        """Mute audio"""
        self.adb.run(["shell", "input", "keyevent", "KEYCODE_VOLUME_MUTE"])
    
    def get_volume(self) -> int:
        """Get current volume level (0-100)"""
        try:
            out = self.adb.run(["shell", "dumpsys", "audio"])
            # Parse volume from dumpsys output
            match = re.search(r'- STREAM_MUSIC:.*?mIndex: (\d+)', out)
            if match:
                return int(match.group(1))
        except Exception:
            pass
        return 50  # Default fallback
    
    def set_volume(self, level: int) -> None:
        """Set volume to specific level (0-100 percentage)"""
        current = self.get_volume()
        target = max(0, min(100, level))
        
        if target > current:
            diff = (target - current) // 7  # Rough conversion
            self.volume_up(max(1, diff))
        elif target < current:
            diff = (current - target) // 7
            self.volume_down(max(1, diff))
    
    # ===========================
    # Media Controls
    # ===========================
    
    def media_play(self) -> None:
        """Play/resume media"""
        self.adb.run(["shell", "input", "keyevent", "KEYCODE_MEDIA_PLAY"])
    
    def media_pause(self) -> None:
        """Pause media"""
        self.adb.run(["shell", "input", "keyevent", "KEYCODE_MEDIA_PAUSE"])
    
    def media_play_pause(self) -> None:
        """Toggle play/pause"""
        self.adb.run(["shell", "input", "keyevent", "KEYCODE_MEDIA_PLAY_PAUSE"])
    
    def media_stop(self) -> None:
        """Stop media playback"""
        self.adb.run(["shell", "input", "keyevent", "KEYCODE_MEDIA_STOP"])
    
    def media_next(self) -> None:
        """Next track/video"""
        self.adb.run(["shell", "input", "keyevent", "KEYCODE_MEDIA_NEXT"])
    
    def media_previous(self) -> None:
        """Previous track/video"""
        self.adb.run(["shell", "input", "keyevent", "KEYCODE_MEDIA_PREVIOUS"])
    
    def media_fast_forward(self) -> None:
        """Fast forward"""
        self.adb.run(["shell", "input", "keyevent", "KEYCODE_MEDIA_FAST_FORWARD"])
    
    def media_rewind(self) -> None:
        """Rewind"""
        self.adb.run(["shell", "input", "keyevent", "KEYCODE_MEDIA_REWIND"])
