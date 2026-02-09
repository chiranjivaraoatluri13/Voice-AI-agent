# =========================
# FILE: agent/qwen_controller.py
# =========================
"""
Complete vision-based controller using Qwen-VL.
Combines real-time capture + on-device vision.
"""

from agent.qwen_vision import QwenVisionEngine, VisionResult
from agent.realtime_screen import RealtimeScreenCapture
from agent.device import DeviceController
from agent.adb import AdbClient
import time


class QwenSmartController:
    """
    Intelligent controller using Qwen-VL for vision understanding.
    """
    
    def __init__(self):
        # Initialize components
        self.adb = AdbClient()
        self.device = DeviceController(self.adb)
        self.vision = QwenVisionEngine()
        self.screen_capture = RealtimeScreenCapture(fps=15)
        
        # Start real-time capture
        self.screen_capture.start()
        
        # Get screen size
        try:
            w, h = self.device.screen_size()
            self.vision.set_screen_size(w, h)
            print(f"📱 Screen: {w}x{h}")
        except:
            print("⚠️ Could not get screen size")
    
    # ===========================
    # High-Level Actions
    # ===========================
    
    def send_message(self, message: str = None):
        """
        Smart send: Finds and taps send button.
        Works across all messaging apps!
        """
        
        print("📤 Looking for send button...")
        
        # Get current frame
        frame_path = self.screen_capture.save_current_frame()
        
        # Find send button with Qwen-VL
        result = self.vision.find_send_button(frame_path)
        
        if result.coordinates and result.confidence > 0.5:
            x, y = result.coordinates
            print(f"✅ Found send button at ({x}, {y})")
            print(f"   Description: {result.description}")
            
            # Type message if provided
            if message:
                self.device.type_text(message)
                time.sleep(0.2)
            
            # Tap send
            self.device.tap(x, y)
            print("✅ Message sent!")
            return True
        
        else:
            print(f"❌ Could not find send button")
            print(f"   Vision said: {result.description}")
            return False
    
    def go_back(self):
        """Smart back: Finds back button visually"""
        
        frame_path = self.screen_capture.save_current_frame()
        result = self.vision.find_back_button(frame_path)
        
        if result.coordinates:
            self.device.tap(*result.coordinates)
            return True
        
        # Fallback to hardware back
        self.device.back()
        return True
    
    def open_menu(self):
        """Smart menu: Finds menu button"""
        
        frame_path = self.screen_capture.save_current_frame()
        result = self.vision.find_menu_button(frame_path)
        
        if result.coordinates:
            self.device.tap(*result.coordinates)
            return True
        
        return False
    
    def find_and_tap(self, description: str):
        """
        Universal tap: Find anything and tap it.
        
        Examples:
        - "subscribe button"
        - "red notification icon"
        - "first video thumbnail"
        """
        
        print(f"🔍 Looking for: {description}")
        
        frame_path = self.screen_capture.save_current_frame()
        result = self.vision.find_icon(frame_path, description)
        
        if result.coordinates and result.confidence > 0.5:
            x, y = result.coordinates
            print(f"✅ Found at ({x}, {y}): {result.description}")
            self.device.tap(x, y)
            return True
        
        else:
            print(f"❌ Could not find: {description}")
            return False
    
    def ask_about_screen(self, question: str) -> str:
        """
        Ask anything about current screen.
        
        Examples:
        - "What app is this?"
        - "Is there a send button?"
        - "What's the main content?"
        """
        
        frame_path = self.screen_capture.save_current_frame()
        result = self.vision.answer_question(frame_path, question)
        
        return result.description
    
    def describe_screen(self) -> str:
        """Get description of current screen"""
        
        frame_path = self.screen_capture.save_current_frame()
        result = self.vision.describe_screen(frame_path)
        
        return result.description


# ===========================
# Example Usage
# ===========================

if __name__ == "__main__":
    
    print("🚀 Starting Qwen-VL Smart Controller...")
    
    controller = QwenSmartController()
    
    # Wait for everything to be ready
    time.sleep(2)
    
    print("\n" + "="*50)
    print("READY! Try these commands:")
    print("="*50)
    
    while True:
        cmd = input("\n> ").strip().lower()
        
        if not cmd:
            continue
        
        if cmd in ['exit', 'quit']:
            break
        
        # Smart commands
        if 'send' in cmd:
            controller.send_message()
        
        elif 'back' in cmd:
            controller.go_back()
        
        elif 'menu' in cmd:
            controller.open_menu()
        
        elif 'find' in cmd or 'tap' in cmd or 'click' in cmd:
            # Extract what to find
            target = cmd.replace('find', '').replace('tap', '').replace('click', '').strip()
            controller.find_and_tap(target)
        
        elif 'what' in cmd or 'describe' in cmd:
            description = controller.describe_screen()
            print(f"\n📱 {description}\n")
        
        else:
            # Generic question
            answer = controller.ask_about_screen(cmd)
            print(f"\n💬 {answer}\n")