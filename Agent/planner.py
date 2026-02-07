# =========================
# FILE: agent/planner_unified.py
# =========================
"""
Unified Natural Language Planner
Uses Intent Engine for ALL interactions
"""

from typing import Optional
from agent.schema import Command
from agent.intent_engine import get_intent_engine


def plan(user_input: str) -> Optional[Command]:
    """
    Main planning function with natural language understanding.
    
    Handles ALL interactions naturally:
    - "pause video" → media control
    - "tap on the video about cats" → vision + tap
    - "send hi to mom in whatsapp" → messaging
    - "open the pin with red car" → pinterest + visual search
    """
    
    # Get intent engine
    engine = get_intent_engine()
    
    # Understand user intent
    intent = engine.understand(user_input)
    
    # Low confidence - didn't understand
    if intent.confidence < 0.5:
        return None
    
    # Convert intent to command
    command = engine.intent_to_command(intent)
    
    # Show what was understood (for debugging/transparency)
    if command and intent.confidence > 0.7:
        print(f"💭 Understood: {intent.primary_action} ({intent.confidence:.0%} confident)")
    
    return command
