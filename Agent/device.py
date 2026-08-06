# =========================
# FILE: agent/device.py
# =========================
import re
import random
import time
from typing import Tuple, Literal, Optional
from agent.adb import AdbClient


class DeviceController:
    # The effective display size is re-checked at most this often (seconds).
    # Keeps the hot path (tap/scroll) fast while still noticing rotation and
    # app-forced orientation changes.
    _SIZE_TTL = 2.0

    def __init__(self, adb: AdbClient) -> None:
        self.adb = adb
        self._cached_screen_size: Optional[Tuple[int, int]] = None
        self._size_time: float = 0.0

    def _read_effective_size(self) -> Optional[Tuple[int, int]]:
        """
        True touch-coordinate size of the CURRENT display, already adjusted for
        rotation AND app-forced orientation.

        `dumpsys display`'s mOverrideDisplayInfo `real WxH` is authoritative: when
        a landscape-locked app (e.g. YouTube) runs on a portrait tablet, this
        reports 1920x1200 even though the tablet is held vertically and
        `wm size` / `user_rotation` still say portrait. Costs ~150ms.
        """
        try:
            out = self.adb.run(["shell", "dumpsys", "display"], timeout=6)
        except Exception:
            return None

        # Prefer the override info (what apps/touch actually use)
        m = re.search(
            r"mOverrideDisplayInfo=DisplayInfo\{.*?\breal (\d+) x (\d+)",
            out, re.DOTALL,
        )
        if not m:
            # Fall back to the base display info
            m = re.search(
                r"mBaseDisplayInfo=DisplayInfo\{.*?\breal (\d+) x (\d+)",
                out, re.DOTALL,
            )
        if m:
            w, h = int(m.group(1)), int(m.group(2))
            if w > 0 and h > 0:
                return (w, h)
        return None

    def _read_panel_size_with_rotation(self) -> Tuple[int, int]:
        """Fallback: `wm size` (natural) swapped by `user_rotation`."""
        out = self.adb.run(["shell", "wm", "size"])
        m = re.search(r"Override size:\s*(\d+)x(\d+)", out)
        if not m:
            m = re.search(r"Physical size:\s*(\d+)x(\d+)", out)
        if not m:
            raise RuntimeError(f"Could not parse screen size from: {out}")
        a, b = int(m.group(1)), int(m.group(2))

        rotation = 0
        try:
            r = self.adb.run(
                ["shell", "settings", "get", "system", "user_rotation"], timeout=4).strip()
            if r.isdigit():
                rotation = int(r) % 4
        except Exception:
            pass
        return (b, a) if rotation in (1, 3) else (a, b)

    def screen_size(self, force_refresh: bool = False) -> Tuple[int, int]:
        """
        Return width/height in the coordinate space used by `input tap/swipe`.

        Reads the effective (rotation- and app-orientation-aware) size from
        `dumpsys display`, falling back to `wm size` + `user_rotation`. Cached for
        _SIZE_TTL seconds so repeated tap/scroll calls stay fast (~150ms once).
        """
        now = time.time()
        if (not force_refresh and self._cached_screen_size is not None
                and (now - self._size_time) < self._SIZE_TTL):
            return self._cached_screen_size

        size = self._read_effective_size()
        if size is None:
            size = self._read_panel_size_with_rotation()

        self._cached_screen_size = size
        self._size_time = now
        return size

    def invalidate_screen_size_cache(self) -> None:
        self._cached_screen_size = None
        self._size_time = 0.0

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
        w, h = self.screen_size()

        if scroll_bounds:
            left, top, right, bottom = scroll_bounds
            # Drop bounds captured before a rotation or from a stale UI tree
            if (
                right <= left or bottom <= top
                or left < -20 or top < -20
                or right > w + 20 or bottom > h + 20
            ):
                scroll_bounds = None

        if scroll_bounds:
            left, top, right, bottom = scroll_bounds
            x = (left + right) // 2
            y_top = top + int((bottom - top) * 0.25)
            y_bot = top + int((bottom - top) * 0.75)
            duration = 650
        else:
            x = w // 2
            if w > h:  # landscape
                y_top = int(h * 0.25)
                y_bot = int(h * 0.75)
                duration = 750
            else:  # portrait
                y_top = int(h * 0.15)
                y_bot = int(h * 0.85)
                duration = 650

        margin = 10
        x = max(margin, min(w - margin, x + random.randint(-10, 10)))
        y_top = max(margin, min(h - margin, y_top))
        y_bot = max(margin, min(h - margin, y_bot))
        if y_top == y_bot:
            y_bot = min(h - margin, y_top + max(100, h // 4))

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

    def volume_min(self) -> None:
        """Lower volume all the way to the minimum."""
        self.volume_down(15)

    def volume_max(self) -> None:
        """Raise volume all the way to the maximum."""
        self.volume_up(15)

    # -------------------------
    # Brightness Controls
    # -------------------------
    def get_brightness(self) -> Optional[int]:
        """Return current screen brightness (0-255) or None if unavailable."""
        try:
            out = self.adb.run(["shell", "settings", "get", "system", "screen_brightness"]).strip()
            return int(out)
        except Exception:
            return None

    def set_brightness(self, value: int) -> None:
        value = max(0, min(255, value))
        self.adb.run(["shell", "settings", "put", "system", "screen_brightness", str(value)])

    def brightness_up(self, step: int = 40) -> None:
        current = self.get_brightness()
        if current is None:
            current = 128
        self.set_brightness(current + step)

    def brightness_down(self, step: int = 40) -> None:
        current = self.get_brightness()
        if current is None:
            current = 128
        self.set_brightness(current - step)

    # -------------------------
    # Screenshot
    # -------------------------
    def screenshot(self, local_path: Optional[str] = None) -> str:
        """Capture a screenshot and pull it to the local machine. Returns local path."""
        import os
        if not local_path:
            local_path = os.path.join(os.getcwd(), f"screenshot_{int(time.time())}.png")
        self.adb.run(["shell", "screencap", "-p", "/sdcard/screenshot.png"])
        self.adb.run(["pull", "/sdcard/screenshot.png", local_path])
        return local_path
