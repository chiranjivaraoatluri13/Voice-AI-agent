# =========================
# FILE: agent/adb.py
# =========================
import subprocess
import shutil
import time
from typing import List

class AdbClient:
    def __init__(self) -> None:
        self.adb = self._resolve_adb()
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 2

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
        # Force UTF-8 encoding to handle emojis and special characters from Android
        p = subprocess.run(
            [self.adb] + args, 
            capture_output=True, 
            text=True,
            encoding='utf-8',
            errors='replace'  # Replace invalid chars instead of crashing
        )
        
        # Check for connection errors
        if p.returncode != 0:
            stderr = p.stderr.strip() if p.stderr else ""
            
            # Auto-reconnect on connection loss
            if any(err in stderr.lower() for err in ["device offline", "error: closed", "no devices", "device not found"]):
                print(f"⚠️  Connection lost: {stderr}")
                
                if self.reconnect_attempts < self.max_reconnect_attempts:
                    if self._try_reconnect():
                        print("✅ Reconnected! Retrying command...")
                        self.reconnect_attempts = 0  # Reset on success
                        
                        # Retry the command once
                        p = subprocess.run(
                            [self.adb] + args,
                            capture_output=True,
                            text=True,
                            encoding='utf-8',
                            errors='replace'
                        )
                        if p.returncode == 0:
                            return p.stdout.strip()
                        stderr = p.stderr.strip() if p.stderr else ""
                
                # Give helpful error message
                raise RuntimeError(
                    f"❌ Device connection lost.\n"
                    f"   Error: {stderr}\n"
                    f"   Fix: Check USB cable or run 'adb devices' manually"
                )
            
            raise RuntimeError(stderr or f"Failed: {[self.adb]+args}")
        
        return p.stdout.strip()
    
    def _try_reconnect(self) -> bool:
        """Attempt to reconnect to device"""
        try:
            self.reconnect_attempts += 1
            print(f"🔄 Reconnect attempt {self.reconnect_attempts}/{self.max_reconnect_attempts}...")
            
            # Kill and restart ADB server
            subprocess.run([self.adb, "kill-server"], capture_output=True, timeout=3)
            time.sleep(0.5)
            subprocess.run([self.adb, "start-server"], capture_output=True, timeout=5)
            time.sleep(1.5)
            
            # Check if device is back
            result = subprocess.run(
                [self.adb, "devices"],
                capture_output=True,
                text=True,
                timeout=3
            )
            
            if "device" in result.stdout and "\tdevice" in result.stdout:
                return True
            
            return False
            
        except Exception as e:
            print(f"⚠️  Reconnect failed: {e}")
            return False

    def ensure_device(self) -> list[str]:
        out = self.run(["devices"])
        lines = [l.strip() for l in out.splitlines() if l.strip()]
        devs = [l for l in lines[1:] if "\tdevice" in l]
        if not devs:
            raise RuntimeError("No ADB device connected (adb devices shows none).")
        return devs
    
    def check_connection(self) -> bool:
        """Check if device is still connected"""
        try:
            result = subprocess.run(
                [self.adb, "devices"],
                capture_output=True,
                text=True,
                timeout=2
            )
            return "device" in result.stdout and "\tdevice" in result.stdout
        except Exception:
            return False
