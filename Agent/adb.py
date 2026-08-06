# =========================
# FILE: agent/adb.py
# =========================
import os
import subprocess
import shutil
import threading
import time
from typing import List, Optional


class AdbClient:
    """
    Serializes ADB access, with foreground priority.

    Background watchers issue long commands (`uiautomator dump` costs ~3s), so
    without priority a user command can sit behind several of them. Foreground
    callers register interest first; background callers wait for a gap.
    """

    def __init__(self) -> None:
        self.adb = self._resolve_adb()
        self._lock = threading.Lock()
        self._state = threading.Condition()
        self._fg_waiting = 0
        self._bg_active = 0
        # Bumped whenever we issue a command that moves the screen. Consumers
        # use it to drop UI snapshots that describe the pre-action screen.
        self.screen_generation = 0
        # Prefer ANDROID_SERIAL if set; otherwise chosen in ensure_device()
        self.serial: Optional[str] = os.environ.get("ANDROID_SERIAL") or None

    def _enter(self, background: bool, max_yield: float = 6.0) -> None:
        if background:
            deadline = time.time() + max_yield
            with self._state:
                while self._fg_waiting > 0 and time.time() < deadline:
                    self._state.wait(timeout=0.05)
                self._bg_active += 1
        else:
            with self._state:
                self._fg_waiting += 1

    def _exit(self, background: bool) -> None:
        with self._state:
            if background:
                self._bg_active = max(0, self._bg_active - 1)
            else:
                self._fg_waiting = max(0, self._fg_waiting - 1)
            self._state.notify_all()

    def wait_idle(self, timeout: float = 4.0) -> bool:
        """Block until no background ADB command is in flight."""
        deadline = time.time() + timeout
        with self._state:
            while self._bg_active > 0 and time.time() < deadline:
                self._state.wait(timeout=0.05)
            return self._bg_active == 0

    def foreground_pending(self) -> bool:
        """True when a user command is waiting on (or holding) the ADB bus.

        Background pollers should check this and skip expensive work: the lock
        is held for a whole command, so starting a ~3s `uiautomator dump` right
        before a user command lands makes that command wait it out.
        """
        with self._state:
            return self._fg_waiting > 0

    def _resolve_adb(self) -> str:
        p = shutil.which("adb")
        if p:
            return p
        for candidate in [r".\adb", r".\adb.exe"]:
            try:
                subprocess.run([candidate, "version"], capture_output=True, text=True)
                return candidate
            except Exception:
                pass
        raise RuntimeError(
            "adb not found. Add platform-tools to PATH or run from the platform-tools folder."
        )

    def _prefix(self, args: List[str]) -> List[str]:
        """Inject -s <serial> when a device is selected (skip global adb commands)."""
        if not self.serial:
            return args
        if not args:
            return args
        head = args[0]
        if head in {
            "devices", "version", "start-server", "kill-server",
            "connect", "disconnect", "help",
        }:
            return args
        if head == "-s":
            return args
        return ["-s", self.serial] + args

    # Commands that change what is on screen, so any cached UI tree is void.
    _MUTATING = ("input", "monkey", "am")

    def _note_if_mutating(self, args: List[str]) -> None:
        try:
            if args and args[0] == "shell" and len(args) > 1 and args[1] in self._MUTATING:
                self.screen_generation += 1
        except Exception:
            pass

    def run(self, args: List[str], timeout: int = 30, background: bool = False) -> str:
        # encoding="utf-8" + errors="replace" prevents Windows cp1252 crashes
        # when ADB output contains non-ASCII characters (app names, file paths, etc.)
        cmd = self._prefix(args)
        self._note_if_mutating(args)
        self._enter(background)
        try:
            with self._lock:
                p = subprocess.run(
                    [self.adb] + cmd,
                    capture_output=True, text=True,
                    encoding="utf-8", errors="replace",
                    timeout=timeout
                )
                if p.returncode != 0:
                    raise RuntimeError(p.stderr.strip() or f"Failed: {[self.adb]+cmd}")
                return p.stdout
        finally:
            self._exit(background)

    def run_binary(self, args: List[str], timeout: int = 30,
                   background: bool = False) -> bytes:
        """Run ADB and return raw binary output (for XML, images, etc)."""
        cmd = self._prefix(args)
        self._enter(background)
        try:
            with self._lock:
                p = subprocess.run(
                    [self.adb] + cmd,
                    capture_output=True,
                    timeout=timeout
                )
                if p.returncode != 0:
                    raise RuntimeError(
                        f"Failed: {[self.adb]+cmd}: {p.stderr.decode('utf-8', errors='replace')}"
                    )
                return p.stdout
        finally:
            self._exit(background)

    def ensure_device(self) -> list[str]:
        out = self.run(["devices"])
        lines = [l.strip() for l in out.splitlines() if l.strip()]
        # Only fully online devices ("device"), ignore offline/unauthorized
        online = []
        for line in lines[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                online.append(parts[0])

        if not online:
            raise RuntimeError(
                "No ADB device connected in 'device' state "
                "(check `adb devices` — offline/unauthorized entries are ignored)."
            )

        # Keep an explicit serial so later commands don't hit
        # "more than one device/emulator" when offline entries remain listed.
        if self.serial and self.serial in online:
            pass
        elif self.serial and self.serial not in online:
            print(
                f"⚠️ ANDROID_SERIAL={self.serial} not online; "
                f"switching to {online[0]}"
            )
            self.serial = online[0]
        else:
            # Prefer USB serials (no ':') over wireless/network endpoints
            usb = [s for s in online if ":" not in s]
            self.serial = usb[0] if usb else online[0]

        try:
            print(f"📱 Using ADB device: {self.serial}")
        except UnicodeEncodeError:
            print(f"[ADB] Using device: {self.serial}")
        return [f"{s}\tdevice" for s in online]
