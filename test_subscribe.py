#!/usr/bin/env python3
"""
Quick test script to debug subscribe/unsubscribe click issue.
Run this to see all elements on screen and test clicking.
"""

import sys
from agent.adb import AdbClient
from agent.device import DeviceController
from agent.screen_controller import ScreenController

def main():
    try:
        adb = AdbClient()
        device = DeviceController(adb)
        screen = ScreenController(adb, device)
        
        print("\n" + "="*80)
        print("SCREEN ELEMENT DEBUGGER")
        print("="*80)
        
        # Show what's on screen
        print("\n1. Current screen elements:")
        print(screen.dump_screen_state())
        
        # Try clicking subscribe
        print("\n2. Attempting to click 'subscribe'...")
        result = screen.execute_query("click subscribe")
        print(f"   Result: {'SUCCESS' if result else 'FAILED'}")
        
        # Wait and check if screen changed
        import time
        time.sleep(1)
        
        print("\n3. New screen state (after click):")
        print(screen.dump_screen_state())
        
        print("\n" + "="*80)
        
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
