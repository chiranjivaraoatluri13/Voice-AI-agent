# =========================
# FILE: agent/task_executor.py
# =========================
"""
Task Executor for Complex Multi-Step Actions
Handles: messaging, searching, app-specific workflows
"""

import time
import json
from typing import Optional
from agent.device import DeviceController
from agent.apps import AppResolver
from agent.screen_controller import ScreenController


class TaskExecutor:
    """
    Executes complex multi-step tasks.
    Example: "send hi to mom in whatsapp" = open app + find contact + type + send
    """
    
    def __init__(
        self,
        device: DeviceController,
        apps: AppResolver,
        screen: ScreenController
    ):
        self.device = device
        self.apps = apps
        self.screen = screen
    
    def execute_task(self, task_json: str) -> bool:
        """
        Execute a complex task from JSON intent.
        
        Args:
            task_json: JSON string with task details
        
        Returns:
            True if successful
        """
        try:
            task = json.loads(task_json)
            action = task.get('primary_action')
            
            if action == "send_message":
                return self._send_message(task)
            
            elif action == "find_and_open":
                return self._find_and_open(task)
            
            elif action == "search":
                return self._search(task)
            
            else:
                print(f"⚠️ Unknown complex task: {action}")
                return False
        
        except Exception as e:
            print(f"❌ Task execution failed: {e}")
            return False
    
    # ===========================
    # MESSAGING
    # ===========================
    
    def _send_message(self, task: dict) -> bool:
        """
        Send a message: "send hi to mom in whatsapp"
        
        Steps:
        1. Open WhatsApp
        2. Find contact
        3. Type message
        4. Send
        """
        recipient = task.get('target')
        message = task.get('text')
        app = task.get('app', 'whatsapp')
        
        print(f"📱 Sending '{message}' to {recipient} via {app}")
        
        # Step 1: Open app
        print(f"   1. Opening {app}...")
        pkg = self.apps.resolve_or_ask(app, allow_learning=False)
        if not pkg:
            print(f"❌ Could not find {app}")
            return False
        
        self.device.launch(pkg)
        time.sleep(2)  # Wait for app to load
        
        # Step 2: Find and tap search/new chat
        print(f"   2. Finding search...")
        success = self.screen.execute_query("tap search icon")
        if not success:
            # Try alternative: tap new chat button
            success = self.screen.execute_query("tap new chat")
        
        if not success:
            print("⚠️ Could not find search. Trying to continue anyway...")
        
        time.sleep(1)
        
        # Step 3: Type recipient name
        print(f"   3. Searching for {recipient}...")
        self.device.type_text(recipient)
        time.sleep(1)
        
        # Step 4: Tap first result
        print(f"   4. Opening chat...")
        success = self.screen.execute_query("tap first result")
        if not success:
            # Try tapping on name
            success = self.screen.execute_query(f"tap {recipient}")
        
        time.sleep(1)
        
        # Step 5: Type message
        print(f"   5. Typing message...")
        self.device.type_text(message)
        time.sleep(0.5)
        
        # Step 6: Send
        print(f"   6. Sending...")
        success = self.screen.execute_query("tap send button")
        
        if success:
            print(f"✅ Message sent to {recipient}!")
            return True
        else:
            print(f"⚠️ Message typed but send button not found. You can send manually.")
            return False
    
    # ===========================
    # VISUAL SEARCH & OPEN
    # ===========================
    
    def _find_and_open(self, task: dict) -> bool:
        """
        Find and open specific content: "open the pin with red car"
        
        Steps:
        1. Open app (Pinterest)
        2. Search for description ("red car")
        3. Tap the result
        """
        item_type = task.get('target')
        description = task.get('description')
        app = task.get('app')
        
        print(f"🔍 Finding {item_type} with: {description}")
        
        # Step 1: Open app if specified
        if app:
            print(f"   1. Opening {app}...")
            pkg = self.apps.resolve_or_ask(app, allow_learning=False)
            if pkg:
                self.device.launch(pkg)
                time.sleep(2)
        
        # Step 2: Search or scroll to find
        print(f"   2. Looking for: {description}...")
        
        # Try direct visual search
        query = f"tap {item_type} with {description}"
        success = self.screen.execute_query(query)
        
        if success:
            print(f"✅ Opened {item_type}!")
            return True
        
        # Try scrolling to find
        print(f"   3. Scrolling to find...")
        query = f"scroll until you find {description}"
        success = self.screen.execute_query(query)
        
        if success:
            print(f"✅ Found and opened!")
            return True
        
        print(f"❌ Could not find {item_type} with {description}")
        return False
    
    # ===========================
    # SEARCH
    # ===========================
    
    def _search(self, task: dict) -> bool:
        """
        Search for content: "search for cat videos on youtube"
        
        Steps:
        1. Open app (YouTube)
        2. Tap search
        3. Type query
        4. Search
        """
        query = task.get('target')
        app = task.get('app')
        
        print(f"🔍 Searching for: {query}")
        
        # Step 1: Open app
        if app:
            print(f"   1. Opening {app}...")
            pkg = self.apps.resolve_or_ask(app, allow_learning=False)
            if pkg:
                self.device.launch(pkg)
                time.sleep(2)
        
        # Step 2: Find and tap search
        print(f"   2. Opening search...")
        success = self.screen.execute_query("tap search")
        if not success:
            success = self.screen.execute_query("tap search icon")
        
        time.sleep(1)
        
        # Step 3: Type query
        print(f"   3. Typing: {query}")
        self.device.type_text(query)
        time.sleep(0.5)
        
        # Step 4: Submit search
        print(f"   4. Searching...")
        self.device.adb.run(["shell", "input", "keyevent", "KEYCODE_ENTER"])
        
        print(f"✅ Search complete!")
        return True
