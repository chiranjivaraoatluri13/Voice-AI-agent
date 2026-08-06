#!/usr/bin/env python3
# =========================
# FILE: test_device_integration.py
# =========================
"""
Quick test of device features integration with controller.py
"""

from agent.adb import AdbClient
from agent.device_features import DeviceFeatureController
from agent.device_command_mapper import DeviceCommandMapper

def test_device_integration():
    """Test that device features integrate properly with the system."""
    print("\n" + "="*60)
    print("DEVICE FEATURES INTEGRATION TEST")
    print("="*60)
    
    try:
        # Initialize
        adb = AdbClient()
        device_features = DeviceFeatureController(adb)
        device_mapper = DeviceCommandMapper(device_features)
        
        print("\n✅ Device features initialized successfully")
        
        # Test device command detection (from controller.py)
        test_commands = [
            "enable wifi",
            "turn on bluetooth", 
            "toggle torch",
            "device status",
            "available features",
            "set brightness to 150",
            "turn on the flashlight",
            "disable location",
        ]
        
        print("\n📋 Testing device command detection & execution:\n")
        
        for cmd in test_commands:
            print(f"> {cmd}")
            try:
                result = device_mapper.execute_device_command(cmd)
                print(f"  {result}\n")
            except Exception as e:
                print(f"  ⚠️ {e}\n")
        
        print("="*60)
        print("✅ Integration test complete!")
        print("="*60 + "\n")
        
    except Exception as e:
        print(f"❌ Integration test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_device_integration()
