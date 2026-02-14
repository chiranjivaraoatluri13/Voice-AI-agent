#!/usr/bin/env python3
"""
Debug script to test UI cache system.
Checks if background cache watcher is working properly.
"""

import time
import sys
from agent.adb import AdbClient
from agent.device import DeviceController
from agent.ui_analyzer import UIAnalyzer
from agent.screen_controller import ScreenController

def main():
    try:
        print("\n" + "="*80)
        print("UI CACHE DIAGNOSTIC - XML PARSING FIX")
        print("="*80)
        
        # Initialize
        adb = AdbClient()
        device = DeviceController(adb)
        ui_analyzer = UIAnalyzer(adb)
        screen = ScreenController(adb, device)
        
        print("\n1. Testing raw ADB XML retrieval...")
        try:
            # Direct binary test
            adb.run(["shell", "uiautomator", "dump", "/sdcard/ui_dump.xml"])
            xml_bytes = adb.run_binary(["shell", "cat", "/sdcard/ui_dump.xml"])
            xml_text = xml_bytes.decode("utf-8", errors="ignore")
            
            print(f"   ✅ Raw XML size: {len(xml_bytes)} bytes")
            print(f"   ✅ Decoded text: {len(xml_text)} chars")
            print(f"   ✅ XML header found: {'<?xml' in xml_text}")
            print(f"   ✅ Contains nodes: {'<node' in xml_text}")
            node_count = xml_text.count("<node")
            print(f"   ✅ Node count: {node_count}")
        except Exception as e:
            print(f"   ❌ Error: {e}")
        
        print("\n2. Cache Watcher Status:")
        print(f"   Running: {ui_analyzer._cache_running}")
        print(f"   Cached elements: {len(ui_analyzer._cached_elements)}")
        print(f"   Thread alive: {ui_analyzer._cache_thread and ui_analyzer._cache_thread.is_alive()}")
        
        # Try live capture with new method
        print("\n3. Testing fixed capture_ui_tree...")
        start = time.time()
        ui_analyzer.capture_ui_tree(force_refresh=True)
        elapsed = time.time() - start
        
        print(f"   Done in {elapsed:.2f}s")
        print(f"   Elements captured: {len(ui_analyzer.last_elements)}")
        
        if ui_analyzer.last_elements:
            clickable = [e for e in ui_analyzer.last_elements if e.clickable or "Button" in e.class_name]
            print(f"   Clickable elements: {len(clickable)}")
            print("\n   First 5 clickable elements:")
            for i, e in enumerate(clickable[:5], 1):
                text = e.text or e.content_desc or "[empty]"
                print(f"      {i}. {text[:50]}")
                if "subscribe" in text.lower():
                    print(f"         ✅ (SUBSCRIBE FOUND!)")
        else:
            print("   ❌ NO ELEMENTS CAPTURED!")
        
        # Check cache
        print("\n4. Cache Status:")
        cached = ui_analyzer.get_cached_elements()
        print(f"   Cached elements: {len(cached)}")
        if cached:
            print(f"   Cache fresh: YES")
        else:
            print(f"   Cache fresh: NO (empty or stale)")
        
        # Test subscribe search
        print("\n5. Testing subscribe search...")
        result = screen.execute_query("click subscribe")
        print(f"   Result: {'✅ SUCCESS' if result else '❌ FAILED'}")
        
        print("\n" + "="*80)
        if ui_analyzer.last_elements:
            print("✅ UI CAPTURE WORKING - Try using the agent now!")
        else:
            print("❌ Still getting empty elements - check logs above")
        print("="*80 + "\n")
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()

