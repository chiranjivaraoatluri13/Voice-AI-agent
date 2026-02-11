# =========================
# FILE: agent/device.py
# =========================
import re
import random
import time
from typing import Tuple, Literal, Optional
from agent.adb import AdbClient


class DeviceController:
    def __init__(self, adb: AdbClient) -> None:
        self.adb = adb
        self._cached_screen_size: Optional[Tuple[int, int]] = None

    def screen_size(self) -> Tuple[int, int]:
        if self._cached_screen_size:
            return self._cached_screen_size
        out = self.adb.run(["shell", "wm", "size"])
        m = re.search(r"(?:Physical|Override) size:\s*(\d+)x(\d+)", out)
        if not m:
            raise RuntimeError(f"Could not parse screen size from: {out}")
        self._cached_screen_size = (int(m.group(1)), int(m.group(2)))
        return self._cached_screen_size

    def invalidate_screen_size_cache(self) -> None:
        self._cached_screen_size = None

    # -------------------------
    # Core actions
    # -------------------------
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

    def tap(self, x: int, y: int, jitter: int = 5) -> None:
        """Tap with ±jitter randomization."""
        jx = x + random.randint(-jitter, jitter)
        jy = y + random.randint(-jitter, jitter)
        try:
            w, h = self.screen_size()
            jx = max(0, min(jx, w))
            jy = max(0, min(jy, h))
        except Exception:
            pass
        self.adb.run(["shell", "input", "tap", str(jx), str(jy)])

    def tap_exact(self, x: int, y: int) -> None:
        self.adb.run(["shell", "input", "tap", str(x), str(y)])

    def long_press(self, x: int, y: int, duration_ms: int = 1000) -> None:
        """Long press at coordinates."""
        self.adb.run(["shell", "input", "swipe", str(x), str(y), str(x), str(y), str(duration_ms)])

    def type_text(self, text: str) -> None:
        """Type text via ADB. Escapes shell-special characters."""
        escaped = text.replace(" ", "%s")
        for ch in ['\\', '"', "'", '`', '(', ')', '&', '|', ';', '<', '>', '$', '!', '~', '{', '}', '[', ']', '*', '?', '#']:
            escaped = escaped.replace(ch, '\\' + ch)
        self.adb.run(["shell", "input", "text", escaped])

    def clear_text_field(self) -> None:
        """
        Clear all text in the focused input field.
        RELIABLE method: move to end, then batch-delete backwards.
        Single ADB call for speed.
        """
        try:
            # Move cursor to end first
            self.adb.run(["shell", "input", "keyevent", "KEYCODE_MOVE_END"])
            time.sleep(0.05)
            # Batch delete: 50 backspaces in one shell command (covers any text length)
            # Single ADB call = fast
            self.adb.run(["shell", 
                "i=0; while [ $i -lt 50 ]; do input keyevent 67; i=$((i+1)); done"])
        except Exception:
            # Ultra-fallback: just a few individual DELs
            for _ in range(20):
                try:
                    self.adb.run(["shell", "input", "keyevent", "67"])
                except Exception:
                    break

    def launch(self, package: str) -> None:
        self.adb.run(["shell", "monkey", "-p", package, "-c",
                       "android.intent.category.LAUNCHER", "1"])
        time.sleep(0.6)

    def close_all_apps(self) -> None:
        """Close all recent apps by opening recents and pressing 'Close all'."""
        try:
            # Open recent apps
            self.adb.run(["shell", "input", "keyevent", "KEYCODE_APP_SWITCH"])
            time.sleep(1.0)
            # Try Samsung "Close all" button (usually at bottom)
            w, h = self.screen_size()
            # Samsung: "Close all" is typically at bottom center
            self.adb.run(["shell", "input", "tap", str(w // 2), str(int(h * 0.95))])
            time.sleep(0.5)
            # Fallback: try AOSP style (swipe each away) - just go home
            self.adb.run(["shell", "input", "keyevent", "KEYCODE_HOME"])
            print("✅ Closed all recent apps")
        except Exception as e:
            print(f"⚠️ Could not close apps: {e}")
            self.home()

    # -------------------------
    # Swipe / scroll
    # -------------------------
    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int) -> None:
        self.adb.run(["shell", "input", "swipe",
                       str(x1), str(y1), str(x2), str(y2), str(duration_ms)])
        time.sleep(0.18)

    def scroll_once(self, direction: Literal["UP", "DOWN"],
                    scroll_bounds: Optional[Tuple[int, int, int, int]] = None) -> None:
        """Scroll within bounds or screen center."""
        if scroll_bounds:
            left, top, right, bottom = scroll_bounds
            x = (left + right) // 2
            y_top = top + int((bottom - top) * 0.25)
            y_bot = top + int((bottom - top) * 0.75)
            duration = 650
        else:
            w, h = self.screen_size()
            x = w // 2
            if w > h:  # landscape
                y_top = int(h * 0.25)
                y_bot = int(h * 0.75)
                duration = 750
            else:
                y_top = int(h * 0.15)
                y_bot = int(h * 0.85)
                duration = 650

        x += random.randint(-10, 10)
        if direction == "DOWN":
            self.swipe(x, y_bot, x, y_top, duration)
        else:
            self.swipe(x, y_top, x, y_bot, duration)

    def scroll_horizontal(self, direction: Literal["LEFT", "RIGHT"],
                          scroll_bounds: Optional[Tuple[int, int, int, int]] = None) -> None:
        if scroll_bounds:
            left, top, right, bottom = scroll_bounds
            y = (top + bottom) // 2
            x_left = left + int((right - left) * 0.20)
            x_right = left + int((right - left) * 0.80)
        else:
            w, h = self.screen_size()
            y = h // 2
            x_left = int(w * 0.15)
            x_right = int(w * 0.85)
        if direction == "LEFT":
            self.swipe(x_right, y, x_left, y, 600)
        else:
            self.swipe(x_left, y, x_right, y, 600)

    # -------------------------
    # Media Controls
    # -------------------------
    def media_play(self) -> None:
        self.adb.run(["shell", "input", "keyevent", "KEYCODE_MEDIA_PLAY"])

    def media_pause(self) -> None:
        self.adb.run(["shell", "input", "keyevent", "KEYCODE_MEDIA_PAUSE"])

    def media_play_pause(self) -> None:
        self.adb.run(["shell", "input", "keyevent", "KEYCODE_MEDIA_PLAY_PAUSE"])

    def media_next(self) -> None:
        self.adb.run(["shell", "input", "keyevent", "KEYCODE_MEDIA_NEXT"])

    def media_previous(self) -> None:
        self.adb.run(["shell", "input", "keyevent", "KEYCODE_MEDIA_PREVIOUS"])

    # -------------------------
    # Volume Controls
    # -------------------------
    def volume_up(self, steps: int = 1) -> None:
        for _ in range(steps):
            self.adb.run(["shell", "input", "keyevent", "KEYCODE_VOLUME_UP"])
            time.sleep(0.1)

    def volume_down(self, steps: int = 1) -> None:
        for _ in range(steps):
            self.adb.run(["shell", "input", "keyevent", "KEYCODE_VOLUME_DOWN"])
            time.sleep(0.1)

    def volume_mute(self) -> None:
        self.adb.run(["shell", "input", "keyevent", "KEYCODE_VOLUME_MUTE"])
