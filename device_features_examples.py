# =========================
# FILE: device_features_examples.py
# =========================
"""
Quick Examples for Device Features Control

Run this file to see device features in action, or copy snippets into your code.

None of these examples modify your existing code - they're standalone.
"""

from agent.adb import AdbClient
from agent.device_features import DeviceFeatureController
from agent.device_command_mapper import DeviceCommandMapper


def example_basic_control() -> None:
    """Example 1: Basic device feature control."""
    print("\n" + "="*60)
    print("EXAMPLE 1: Basic Device Control")
    print("="*60)

    try:
        adb = AdbClient()
        device = DeviceFeatureController(adb)

        print("\n✓ Enabling WiFi...")
        device.wifi_enable()

        print("✓ Disabling Bluetooth...")
        device.bluetooth_disable()

        print("✓ Turning on torch/flashlight...")
        device.torch_enable()

        print("✓ Launching camera...")
        device.camera_launch()

        print("\n✅ Basic control example complete!")

    except Exception as e:
        print(f"❌ Error: {e}")


def example_get_status() -> None:
    """Example 2: Get device status."""
    print("\n" + "="*60)
    print("EXAMPLE 2: Check Device Status")
    print("="*60)

    try:
        adb = AdbClient()
        device = DeviceFeatureController(adb)

        print("\n📊 Checking individual feature statuses:")
        print(f"  WiFi: {device.wifi_status()}")
        print(f"  Bluetooth: {device.bluetooth_status()}")
        print(f"  Location: {device.location_status() if hasattr(device, 'location_status') else 'N/A'}")

        print("\n📱 Full device status:")
        print(device.get_status_string())

    except Exception as e:
        print(f"❌ Error: {e}")


def example_natural_language_commands() -> None:
    """Example 3: Use natural language commands."""
    print("\n" + "="*60)
    print("EXAMPLE 3: Natural Language Commands")
    print("="*60)

    try:
        adb = AdbClient()
        device = DeviceFeatureController(adb)
        mapper = DeviceCommandMapper(device)

        commands = [
            "enable wifi",
            "turn on bluetooth",
            "toggle airplane mode",
            "enable the torch",
            "disable do not disturb",
            "set brightness to 150",
            "launch camera",
            "device status",
        ]

        for cmd in commands:
            print(f"\n> {cmd}")
            result = mapper.execute_device_command(cmd)
            print(f"  {result}")

        print("\n✅ Natural language example complete!")

    except Exception as e:
        print(f"❌ Error: {e}")


def example_batch_operations() -> None:
    """Example 4: Batch enable/disable multiple features."""
    print("\n" + "="*60)
    print("EXAMPLE 4: Batch Operations")
    print("="*60)

    try:
        adb = AdbClient()
        device = DeviceFeatureController(adb)

        print("\n🔄 Enabling multiple features at once:")
        results = device.enable_multiple(["wifi", "bluetooth", "location"])
        for feature, success in results.items():
            status = "✅" if success else "❌"
            print(f"  {status} {feature}")

        print("\n🔄 Disabling multiple features at once:")
        results = device.disable_multiple(["vibration", "haptic_feedback"])
        for feature, success in results.items():
            status = "✅" if success else "❌"
            print(f"  {status} {feature}")

        print("\n✅ Batch operations example complete!")

    except Exception as e:
        print(f"❌ Error: {e}")


def example_screen_control() -> None:
    """Example 5: Screen and display control."""
    print("\n" + "="*60)
    print("EXAMPLE 5: Screen & Display Control")
    print("="*60)

    try:
        adb = AdbClient()
        device = DeviceFeatureController(adb)

        print("\n📺 Controlling display settings:")

        print("  ✓ Enable auto-rotate...")
        device.auto_rotate_enable()

        print("  ✓ Set brightness to 200 (max)...")
        device.screen_brightness_set(200)

        print("  ✓ Set screen timeout to 1 minute...")
        device.screen_timeout_set(60)

        print("\n✅ Screen control example complete!")

    except Exception as e:
        print(f"❌ Error: {e}")


def example_connectivity() -> None:
    """Example 6: Connectivity control."""
    print("\n" + "="*60)
    print("EXAMPLE 6: Connectivity Control")
    print("="*60)

    try:
        adb = AdbClient()
        device = DeviceFeatureController(adb)

        print("\n📡 Controlling connectivity:")

        print("  ✓ Enable WiFi...")
        device.wifi_enable()

        print("  ✓ Enable Bluetooth...")
        device.bluetooth_enable()

        print("  ✓ Enable NFC...")
        device.nfc_enable()

        print("  ✓ Disable mobile data...")
        device.mobile_data_disable()

        print("\n✅ Connectivity example complete!")

    except Exception as e:
        print(f"❌ Error: {e}")


def example_available_features() -> None:
    """Example 7: List all available features."""
    print("\n" + "="*60)
    print("EXAMPLE 7: All Available Features")
    print("="*60)

    try:
        adb = AdbClient()
        device = DeviceFeatureController(adb)
        device.print_available_features()

    except Exception as e:
        print(f"❌ Error: {e}")


def example_toggle_features() -> None:
    """Example 8: Toggle features on/off."""
    print("\n" + "="*60)
    print("EXAMPLE 8: Toggle Features")
    print("="*60)

    try:
        adb = AdbClient()
        device = DeviceFeatureController(adb)

        features_to_toggle = ["wifi", "bluetooth", "airplane_mode", "nfc"]

        print("\n🔄 Toggling features:")
        for feature in features_to_toggle:
            print(f"  ✓ Toggle {feature}...")
            device.feature_toggle(feature)

        print("\n✅ Toggle example complete!")

    except Exception as e:
        print(f"❌ Error: {e}")


def example_parse_commands() -> None:
    """Example 9: Parse and understand natural language."""
    print("\n" + "="*60)
    print("EXAMPLE 9: Command Parsing")
    print("="*60)

    try:
        adb = AdbClient()
        device = DeviceFeatureController(adb)
        mapper = DeviceCommandMapper(device)

        test_inputs = [
            "enable wifi",
            "turn on bluetooth",
            "set brightness to 100",
            "toggle airplane mode",
            "take a photo",
            "launch camera",
            "device status",
        ]

        print("\n🔍 How commands are parsed:")
        for cmd in test_inputs:
            parsed = mapper.parse_device_command(cmd)
            if parsed:
                action, feature, param = parsed
                print(f"  '{cmd}'")
                print(f"    → Action: {action}, Feature: {feature}, Param: {param}")

        print("\n✅ Parsing example complete!")

    except Exception as e:
        print(f"❌ Error: {e}")


# ========================================================
# MENU SYSTEM
# ========================================================

def show_menu() -> None:
    """Show interactive menu."""
    print("\n" + "="*60)
    print("DEVICE FEATURES EXAMPLES")
    print("="*60)
    print("\nChoose an example to run:")
    print("  1. Basic device control")
    print("  2. Check device status")
    print("  3. Natural language commands")
    print("  4. Batch operations")
    print("  5. Screen & display control")
    print("  6. Connectivity control")
    print("  7. List all available features")
    print("  8. Toggle features")
    print("  9. Command parsing demo")
    print("  0. Run all examples")
    print("  q. Quit")
    print()


def main() -> None:
    """Main menu."""
    examples = {
        "1": ("Basic device control", example_basic_control),
        "2": ("Check device status", example_get_status),
        "3": ("Natural language commands", example_natural_language_commands),
        "4": ("Batch operations", example_batch_operations),
        "5": ("Screen & display control", example_screen_control),
        "6": ("Connectivity control", example_connectivity),
        "7": ("List all available features", example_available_features),
        "8": ("Toggle features", example_toggle_features),
        "9": ("Command parsing demo", example_parse_commands),
        "0": ("Run all examples", None),
    }

    while True:
        show_menu()
        choice = input("Enter your choice: ").strip().lower()

        if choice == "q":
            print("👋 Goodbye!")
            break

        if choice == "0":
            for name, func in examples.values()[:-1]:  # type: ignore
                if func:
                    func()
                    input("\nPress Enter to continue...")
            continue

        if choice in examples:
            name, func = examples[choice]
            print(f"\n▶️  Running: {name}")
            if func:
                func()
            input("\nPress Enter to continue...")
        else:
            print("❌ Invalid choice. Please try again.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Interrupted. Goodbye!")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
