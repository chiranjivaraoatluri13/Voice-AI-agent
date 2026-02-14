#!/usr/bin/env python3
"""
Quick ADB connectivity test and device state checker.
"""

import subprocess
import sys

def run_cmd(cmd):
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
    except Exception as e:
        return False, "", str(e)

def main():
    print("\n" + "="*80)
    print("ADB CONNECTIVITY CHECK")
    print("="*80)
    
    # Check if adb is available
    print("\n1. Checking ADB availability...")
    ok, out, err = run_cmd("adb version")
    if ok:
        print(f"   ✅ ADB found")
        print(f"   Version: {out.split(chr(10))[0]}")
    else:
        print(f"   ❌ ADB not found: {err}")
        return
    
    # List devices
    print("\n2. Connected devices:")
    ok, out, err = run_cmd("adb devices")
    if ok:
        devices = [l for l in out.split('\n')[1:] if l.strip() and not l.startswith('*')]
        if devices:
            for dev in devices:
                print(f"   ✅ {dev}")
        else:
            print(f"   ⚠️ No devices connected")
            print("\n   Make sure device is connected with USB debugging enabled")
            return
    
    # Get first device
    devices = [l.split()[0] for l in out.split('\n')[1:] if l.strip() and not l.startswith('*')]
    if not devices:
        print("   No devices to test")
        return
    
    device = devices[0]
    print(f"\n3. Testing device: {device}")
    
    # Check screen state
    print("\n4. Device screen state:")
    ok, out, err = run_cmd(f"adb -s {device} shell getprop ro.serialno")
    if ok:
        print(f"   ✅ Device responsive")
    
    # Try UI dump
    print("\n5. Attempting UI dump:")
    ok, out, err = run_cmd(f"adb -s {device} shell uiautomator dump /sdcard/ui_dump.xml")
    if ok:
        print(f"   ✅ UI dump successful")
        ok2, out2, err2 = run_cmd(f"adb -s {device} shell cat /sdcard/ui_dump.xml")
        if ok2 and "<?xml" in out2:
            lines = out2.count("\n")
            print(f"   ✅ XML retrieved ({lines} lines)")
        else:
            print(f"   ⚠️ Could not retrieve XML")
    else:
        print(f"   ❌ UI dump failed: {err}")
    
    print("\n" + "="*80)
    print("If all checks passed, your ADB connection is working.")
    print("The 'UI tree is empty' error might be due to app state or timing.")
    print("\nTry:")
    print("  1. python test_cache_debug.py  - Detailed cache diagnostic")
    print("  2. Make sure a UI element (like YouTube) is open on device")
    print("="*80 + "\n")

if __name__ == "__main__":
    main()
