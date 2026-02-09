# =========================
# FILE: agent/device.py
# =========================
import re
import time
from typing import Tuple, Literal
from agent.adb import AdbClient

class DeviceController:
    def __init__(self, adb: AdbClient) -> None:
        self.adb = adb

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
        # monkey is simple and widely supported
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
        """
        Single swipe, size-agnostic.
        (Landscape scroll-down edge cases can be handled later.)
        """
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
