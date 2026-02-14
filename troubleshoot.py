#!/usr/bin/env python3
"""
TROUBLESHOOTING GUIDE: "UI tree is empty" error

This script helps diagnose why UI elements are not being captured.
"""

import subprocess
import time
import sys

print("""
================================================================================
TROUBLESHOOTING: "UI tree is empty" Error
================================================================================

This error means the cache/UI tree is not capturing any elements from the device.

POSSIBLE CAUSES:
  1. ❌ Device not connected or ADB connection broken
  2. ❌ UI Automator service not working on device  
  3. ❌ No app/screen is active on device
  4. ❌ Device screen is locked
  5. ❌ XML parsing error (corrupted response)

STEP-BY-STEP FIX:
================================================================================
""")

def step(num, title):
    print(f"\n[STEP {num}] {title}")
    print("-" * 80)

def check_cmd(cmd, description):
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            print(f"  ✅ {description}")
            return True, result.stdout
        else:
            print(f"  ❌ {description}")
            if result.stderr:
                print(f"     Error: {result.stderr[:100]}")
            return False, result.stderr
    except Exception as e:
        print(f"  ❌ {description}: {e}")
        return False, str(e)

# Step 1: Check ADB
step(1, "Check ADB Connection")
ok, out = check_cmd("adb devices", "List connected devices")
if not ok:
    print("\n  💡 FIX: Make sure Android SDK tools are in PATH")
    print("     See: https://developer.android.com/studio/command-line/adb")
    sys.exit(1)

devices = [l.split()[0] for l in out.split('\n')[1:] if 'device' in l and not 'emulator' in l.split()[0]]
if not devices:
    print("\n  ❌ NO DEVICES FOUND!")
    print("\n  💡 FIX:")
    print("     1. Connect Android device via USB")
    print("     2. Enable USB Debugging (Settings → Developer Options)")
    print("     3. Authorize connection when prompted on device")
    print("     4. Run: adb devices")
    sys.exit(1)

device = devices[0]
print(f"\n  Using device: {device}")

# Step 2: Check device responsiveness
step(2, "Check Device Responsiveness")
ok, out = check_cmd(f"adb -s {device} shell getprop ro.build.version.release", "Get Android version")
if not ok:
    print("\n  💡 FIX: Device may be locked. Unlock and retry.")
    sys.exit(1)

# Step 3: Check screen state
step(3, "Check Device Screen State")
ok, out = check_cmd(
    f"adb -s {device} shell 'dumpsys input_method | grep -E \"mInputShown|mIsSurfaceShown\"'",
    "Check if screen is on/visible"
)

# Step 4: Launch an app
step(4, "Launch YouTube App (Test UI Capture)")
ok, out = check_cmd(
    f"adb -s {device} shell monkey -p com.google.android.youtube -c android.intent.category.LAUNCHER 1",
    "Launch YouTube"
)
time.sleep(3)

# Step 5: Try UI dump
step(5, "Capture UI Tree")
ok, out = check_cmd(
    f"adb -s {device} shell uiautomator dump /sdcard/ui_dump.xml",
    "Create UI dump"
)
if not ok:
    print("\n  ❌ UI Automator failed!")
    print("  💡 FIX:")
    print("     1. Try: adb shell uiautomator dump /sdcard/ui_dump.xml")
    print("     2. If error, your device may not support UI Automator")
    print("     3. Try restarting device or switching to a different app")
    sys.exit(1)

# Step 6: Read XML
step(6, "Retrieve UI XML")
ok, out = check_cmd(
    f"adb -s {device} shell cat /sdcard/ui_dump.xml",
    "Read XML file"
)
if "<?xml" not in out:
    print("\n  ❌ Invalid XML response!")
    print(f"  Response preview: {out[:200]}")
    sys.exit(1)

print(f"  ✅ Valid XML ({out.count(chr(10))} lines)")

# Step 7: Check for elements
step(7, "Check for UI Elements in XML")
if "<node" in out:
    node_count = out.count("<node")
    print(f"  ✅ Found {node_count} UI nodes in XML")
    
    # Check for buttons
    if "Button" in out or "button" in out:
        print(f"  ✅ Found button elements")
    if "subscribe" in out.lower():
        print(f"  ✅ Found 'subscribe' in XML!")
else:
    print(f"  ❌ No UI nodes found in XML!")
    print("\n  💡 FIX:")
    print("     1. Make sure an app is fully loaded (not splash screen)")
    print("     2. Try: adb shell uiautomator dump /sdcard/ui_dump.xml")
    print("     3. Then: adb shell cat /sdcard/ui_dump.xml | head -50")
    print("     4. Check if XML contains nodes")

print("\n" + "="*80)
print("✅ DIAGNOSIS COMPLETE")
print("="*80)
print("\nIf all steps passed but code still fails:")
print("  • Run: python test_cache_debug.py")
print("  • This tests the Python code directly")
print("="*80 + "\n")
