# =========================
# FILE: agent/adb.py
# =========================
import subprocess
import shutil
from typing import List

class AdbClient:
    def __init__(self) -> None:
        self.adb = self._resolve_adb()

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

    def run(self, args: List[str]) -> str:
        # encoding="utf-8" + errors="replace" prevents Windows cp1252 crashes
        # when ADB output contains non-ASCII characters (app names, file paths, etc.)
        p = subprocess.run(
            [self.adb] + args,
            capture_output=True, text=True,
            encoding="utf-8", errors="replace"
        )
        if p.returncode != 0:
            raise RuntimeError(p.stderr.strip() or f"Failed: {[self.adb]+args}")
        return p.stdout
    
    def run_binary(self, args: List[str]) -> bytes:
        """Run ADB and return raw binary output (for XML, images, etc)."""
        p = subprocess.run(
            [self.adb] + args,
            capture_output=True
        )
        if p.returncode != 0:
            raise RuntimeError(f"Failed: {[self.adb]+args}: {p.stderr.decode('utf-8', errors='replace')}")
        return p.stdout

    def ensure_device(self) -> list[str]:
        out = self.run(["devices"])
        lines = [l.strip() for l in out.splitlines() if l.strip()]
        devs = [l for l in lines[1:] if "\tdevice" in l]
        if not devs:
            raise RuntimeError("No ADB device connected (adb devices shows none).")
        return devs
