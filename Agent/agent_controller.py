# =========================
# FILE: agent/agent_controller.py
# =========================
"""
Main Agent Controller
Integrates: Semantic Router → Dialogue Manager → Skill Executor
Following the design document architecture
"""

from agent.skill import SkillMemory, Skill
from agent.dialogue_manager import DialogueManager, DialogueState
from agent.semantic_router import SemanticRouter
from agent.device import DeviceController
from agent.apps import AppResolver
from typing import Optional


class AgentController:
    """
    Main agent that orchestrates:
    - Semantic skill routing
    - Dialogue management
    - Skill execution
    """
    
    def __init__(
        self,
        device: DeviceController,
        apps: AppResolver
    ):
        # Core components
        self.device = device
        self.apps = apps
        
        # New architecture components
        self.skill_memory = SkillMemory()
        self.router = SemanticRouter(self.skill_memory)
        self.dialogue = DialogueManager()
        
        print("🤖 Agent initialized with skill-based architecture")
        print(f"📚 Loaded {len(self.skill_memory.list_skills())} skills")
    
    # === MAIN CONVERSATION LOOP ===
    
    def process_input(self, user_input: str) -> str:
        """
        Main entry point for processing user input.
        
        Returns: Response message to display to user
        """
        
        # Check dialogue state
        state = self.dialogue.get_state()
        
        # Handle stateful responses
        if state == DialogueState.AWAITING_CONFIRMATION:
            return self._handle_confirmation(user_input)
        
        if state == DialogueState.AWAITING_CLARIFICATION:
            return self._handle_clarification(user_input)
        
        if state == DialogueState.AWAITING_SPELLING:
            return self._handle_spelling(user_input)
        
        # Handle special commands
        if self._is_repeat_command(user_input):
            return self._handle_repeat()
        
        # Normal flow: Route → Decide → Execute
        return self._route_and_execute(user_input)
    
    # === ROUTING & EXECUTION ===
    
    def _route_and_execute(self, user_input: str) -> str:
        """Route input to skill and execute based on confidence"""
        
        # Route to skills
        matched_skills = self.router.route(user_input, top_k=5)
        
        # Get dialogue manager decision
        decision = self.dialogue.route_user_input(user_input, matched_skills)
        
        action = decision["action"]
        message = decision["message"]
        
        # Execute immediately
        if action == "execute":
            skill_id = decision["skill_id"]
            result = self._execute_skill(skill_id)
            
            if result["success"]:
                self.dialogue.mark_executed(skill_id)
                return message
            else:
                error = self.dialogue.handle_execution_error(
                    decision.get("skill_name", "task"),
                    result["error"]
                )
                return error["message"]
        
        # Ask for confirmation
        if action == "confirm":
            return message
        
        # Ask for clarification
        if action == "clarify":
            return message
        
        # Request spelling
        if action == "spell":
            return message
        
        # Error
        if action == "error":
            return message
        
        return "🤔 I'm not sure what to do with that."
    
    def _execute_skill(self, skill_id: str) -> dict:
        """
        Execute a skill's procedure.
        
        Returns:
            {"success": bool, "error": str (if failed)}
        """
        skill = self.skill_memory.get_skill(skill_id)
        if not skill:
            return {"success": False, "error": "Skill not found"}
        
        try:
            # Execute based on procedure type
            if skill.procedure_type == "app_launch":
                # Launch app
                if skill.target_package:
                    self.device.launch(skill.target_package)
                    skill.update_usage(success=True)
                    self.skill_memory.save()
                    return {"success": True}
                else:
                    return {"success": False, "error": "No target package specified"}
            
            elif skill.procedure_type == "ui_sequence":
                # Execute UI steps
                for step in skill.ui_steps:
                    self._execute_ui_step(step)
                
                skill.update_usage(success=True)
                self.skill_memory.save()
                return {"success": True}
            
            else:
                return {"success": False, "error": f"Unknown procedure type: {skill.procedure_type}"}
        
        except Exception as e:
            skill.update_usage(success=False)
            self.skill_memory.save()
            return {"success": False, "error": str(e)}
    
    def _execute_ui_step(self, step: dict):
        """Execute a single UI automation step"""
        action = step.get("action")
        
        if action == "launch_app":
            self.device.launch(step["package"])
        
        elif action == "tap":
            # This would use UI Automator or coordinates
            x, y = step.get("x"), step.get("y")
            if x and y:
                self.device.tap(x, y)
        
        elif action == "type":
            self.device.type_text(step.get("text", ""))
        
        elif action == "scroll":
            direction = step.get("direction", "DOWN")
            self.device.scroll_once(direction)
        
        elif action == "wait":
            import time
            time.sleep(step.get("ms", 500) / 1000.0)
        
        elif action == "back":
            self.device.back()
        
        elif action == "home":
            self.device.home()
    
    # === STATE HANDLING ===
    
    def _handle_confirmation(self, user_response: str) -> str:
        """Handle user's confirmation response"""
        decision = self.dialogue.handle_confirmation_response(user_response)
        
        if decision["action"] == "execute":
            result = self._execute_skill(decision["skill_id"])
            if result["success"]:
                return decision["message"]
            else:
                return f"⚠️ {result['error']}"
        
        elif decision["action"] == "reprocess":
            # User gave new input
            return self._route_and_execute(decision["new_input"])
        
        else:
            return decision["message"]
    
    def _handle_clarification(self, user_response: str) -> str:
        """Handle user's clarification response"""
        decision = self.dialogue.handle_clarification_response(user_response)
        
        if decision["action"] == "execute":
            result = self._execute_skill(decision["skill_id"])
            if result["success"]:
                return decision["message"]
            else:
                return f"⚠️ {result['error']}"
        
        elif decision["action"] == "reprocess":
            return self._route_and_execute(decision["new_input"])
        
        elif decision["action"] == "cancel":
            return decision["message"]
        
        else:
            return decision["message"]
    
    def _handle_spelling(self, user_response: str) -> str:
        """Handle spelling/explicit input"""
        # Treat as fresh input
        self.dialogue.reset_context()
        return self._route_and_execute(user_response)
    
    # === SPECIAL COMMANDS ===
    
    def _is_repeat_command(self, user_input: str) -> bool:
        """Check if user wants to repeat last action"""
        repeat_phrases = ["do it again", "repeat", "do that again", "again", "one more time"]
        return any(phrase in user_input.lower() for phrase in repeat_phrases)
    
    def _handle_repeat(self) -> str:
        """Repeat last executed skill"""
        if not self.dialogue.can_repeat_last():
            return "❌ Nothing to repeat. I haven't done anything yet."
        
        last_skill_id = self.dialogue.get_last_skill()
        result = self._execute_skill(last_skill_id)
        
        skill = self.skill_memory.get_skill(last_skill_id)
        skill_name = skill.name if skill else "that"
        
        if result["success"]:
            return f"✅ Repeated: {skill_name}"
        else:
            return f"⚠️ Couldn't repeat {skill_name}: {result['error']}"
    
    # === SKILL MANAGEMENT ===
    
    def teach_skill(
        self,
        name: str,
        description: str,
        example_phrases: list,
        procedure_type: str = "app_launch",
        **kwargs
    ) -> str:
        """
        Teach the agent a new skill.
        
        This is how users extend the agent's capabilities.
        """
        import re
        
        # Generate skill ID
        skill_id = re.sub(r'[^a-z0-9_.]', '', name.lower().replace(' ', '_'))
        skill_id = f"user.{skill_id}"
        
        # Create skill
        skill = Skill(
            skill_id=skill_id,
            name=name,
            description=description,
            canonical_intent=skill_id,
            example_phrases=example_phrases,
            procedure_type=procedure_type,
            **kwargs
        )
        
        # Add to memory
        self.skill_memory.add_skill(skill)
        
        return f"✅ Learned new skill: {name}\n💡 Try saying: {example_phrases[0]}"
    
    def list_skills(self) -> str:
        """List all known skills"""
        skills = self.skill_memory.list_skills()
        
        if not skills:
            return "📚 No skills learned yet."
        
        output = f"📚 Known Skills ({len(skills)}):\n\n"
        
        for skill in skills:
            output += f"• {skill.name}\n"
            output += f"  {skill.description}\n"
            if skill.usage_count > 0:
                output += f"  Used {skill.usage_count} times ({skill.success_rate:.0%} success)\n"
            output += f"  Examples: {', '.join(skill.example_phrases[:2])}\n\n"
        
        return output
    
    def forget_skill(self, skill_name_or_id: str) -> str:
        """Remove a skill from memory"""
        # Try as ID first
        if self.skill_memory.remove_skill(skill_name_or_id):
            return f"✅ Forgot: {skill_name_or_id}"
        
        # Try to find by name
        for skill in self.skill_memory.list_skills():
            if skill.name.lower() == skill_name_or_id.lower():
                self.skill_memory.remove_skill(skill.skill_id)
                return f"✅ Forgot: {skill.name}"
        
        return f"❌ Couldn't find skill: {skill_name_or_id}"
