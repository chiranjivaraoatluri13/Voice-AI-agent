# =========================
# FILE: agent/dialogue_manager.py
# =========================
"""
Dialogue Manager (Behavior Engine)
Deterministic state machine controlling conversation flow
"""

from typing import Optional, List, Tuple
from dataclasses import dataclass
from enum import Enum


class DialogueState(Enum):
    """Current conversation state"""
    IDLE = "idle"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    AWAITING_CLARIFICATION = "awaiting_clarification"
    AWAITING_SPELLING = "awaiting_spelling"
    EXECUTING = "executing"
    ERROR_RECOVERY = "error_recovery"


@dataclass
class DialogueContext:
    """Short-term conversational context"""
    state: DialogueState = DialogueState.IDLE
    clarification_count: int = 0
    last_user_input: Optional[str] = None
    pending_skill_id: Optional[str] = None
    pending_skill_name: Optional[str] = None
    candidate_skills: List[Tuple[float, str, str]] = None  # [(score, id, name)]
    last_executed_skill: Optional[str] = None
    error_message: Optional[str] = None
    
    def reset(self):
        """Reset context for new conversation"""
        self.state = DialogueState.IDLE
        self.clarification_count = 0
        self.last_user_input = None
        self.pending_skill_id = None
        self.pending_skill_name = None
        self.candidate_skills = None
        self.error_message = None


class DialogueManager:
    """
    Deterministic conversation controller.
    Handles clarification, confirmation, and error recovery.
    """
    
    # Confidence thresholds
    HIGH_CONFIDENCE = 0.85  # Auto-execute
    MEDIUM_CONFIDENCE = 0.60  # Ask confirmation
    LOW_CONFIDENCE = 0.35  # Ask clarification
    
    def __init__(self):
        self.context = DialogueContext()
    
    # === SKILL ROUTING ===
    
    def route_user_input(
        self, 
        user_input: str, 
        matched_skills: List[Tuple[float, str, str]]  # [(score, skill_id, skill_name)]
    ) -> dict:
        """
        Route user input based on matched skills and confidence.
        
        Returns dict with:
        - action: "execute", "confirm", "clarify", "spell", "error"
        - message: What to say to user
        - skill_id: Which skill to execute (if any)
        - options: List of options (for clarification)
        """
        
        self.context.last_user_input = user_input
        
        # No matches
        if not matched_skills:
            return self._handle_no_match()
        
        top_score, top_id, top_name = matched_skills[0]
        
        # High confidence - execute immediately
        if top_score >= self.HIGH_CONFIDENCE:
            return {
                "action": "execute",
                "message": f"✅ {top_name}",
                "skill_id": top_id,
                "confidence": top_score
            }
        
        # Medium confidence - ask confirmation
        if top_score >= self.MEDIUM_CONFIDENCE:
            self.context.state = DialogueState.AWAITING_CONFIRMATION
            self.context.pending_skill_id = top_id
            self.context.pending_skill_name = top_name
            
            return {
                "action": "confirm",
                "message": f"🤔 Did you want me to: {top_name}?",
                "skill_id": top_id,
                "confidence": top_score
            }
        
        # Low confidence - offer choices or ask clarification
        if top_score >= self.LOW_CONFIDENCE:
            self.context.state = DialogueState.AWAITING_CLARIFICATION
            self.context.candidate_skills = matched_skills[:3]
            
            return {
                "action": "clarify",
                "message": self._build_clarification_message(matched_skills[:3]),
                "options": [(skill_id, skill_name) for _, skill_id, skill_name in matched_skills[:3]],
                "confidence": top_score
            }
        
        # Very low confidence - escalate
        return self._handle_low_confidence()
    
    # === CONFIRMATION HANDLING ===
    
    def handle_confirmation_response(self, user_response: str) -> dict:
        """
        Handle user's response to confirmation question.
        Expects: "yes", "no", or new input
        """
        response_lower = user_response.lower().strip()
        
        # Positive confirmation
        if any(word in response_lower for word in ["yes", "yeah", "yep", "sure", "ok", "okay", "correct", "right"]):
            skill_id = self.context.pending_skill_id
            skill_name = self.context.pending_skill_name
            self.context.reset()
            
            return {
                "action": "execute",
                "message": f"✅ {skill_name}",
                "skill_id": skill_id
            }
        
        # Negative confirmation
        if any(word in response_lower for word in ["no", "nope", "nah", "wrong", "incorrect"]):
            self.context.reset()
            
            return {
                "action": "clarify",
                "message": "❌ Got it. What did you want me to do?",
                "prompt_user": True
            }
        
        # User provided new input instead
        self.context.reset()
        return {
            "action": "reprocess",
            "message": "💡 Let me try that instead...",
            "new_input": user_response
        }
    
    # === CLARIFICATION HANDLING ===
    
    def handle_clarification_response(self, user_response: str) -> dict:
        """
        Handle user's response to clarification.
        Could be: number selection, new description, or "none"
        """
        response = user_response.strip()
        
        # Number selection
        if response.isdigit():
            choice = int(response)
            if 1 <= choice <= len(self.context.candidate_skills):
                _, skill_id, skill_name = self.context.candidate_skills[choice - 1]
                self.context.reset()
                
                return {
                    "action": "execute",
                    "message": f"✅ {skill_name}",
                    "skill_id": skill_id
                }
            else:
                return {
                    "action": "error",
                    "message": "❌ Invalid choice. Please pick a number from the list."
                }
        
        # Cancel
        if response.lower() in ["0", "cancel", "none", "nevermind"]:
            self.context.reset()
            return {
                "action": "cancel",
                "message": "✅ Cancelled. What else can I help with?"
            }
        
        # New description - reprocess
        self.context.clarification_count += 1
        
        if self.context.clarification_count >= 2:
            # Too many clarifications - ask for spelling
            self.context.state = DialogueState.AWAITING_SPELLING
            return {
                "action": "spell",
                "message": "🔤 I'm still having trouble. Could you spell out exactly what you want? Or type 'cancel' to stop."
            }
        
        self.context.reset()
        return {
            "action": "reprocess",
            "message": "💡 Let me search for that...",
            "new_input": user_response
        }
    
    # === ERROR HANDLING ===
    
    def handle_execution_error(self, skill_name: str, error: str) -> dict:
        """Handle execution failure"""
        self.context.state = DialogueState.ERROR_RECOVERY
        self.context.error_message = error
        
        return {
            "action": "error",
            "message": f"⚠️ I tried to {skill_name}, but something went wrong: {error}",
            "suggest_retry": True
        }
    
    # === HELPERS ===
    
    def _handle_no_match(self) -> dict:
        """Handle case where no skills match"""
        self.context.clarification_count += 1
        
        if self.context.clarification_count == 1:
            return {
                "action": "clarify",
                "message": "🤔 I didn't catch that. What are you looking for?"
            }
        elif self.context.clarification_count == 2:
            return {
                "action": "spell",
                "message": "🔤 I still didn't understand. Could you spell it out or rephrase?"
            }
        else:
            self.context.reset()
            return {
                "action": "error",
                "message": "❌ I'm sorry, I couldn't understand. You can teach me new commands with: 'teach me to <action>'"
            }
    
    def _handle_low_confidence(self) -> dict:
        """Handle very low confidence matches"""
        self.context.clarification_count += 1
        
        if self.context.clarification_count == 1:
            return {
                "action": "clarify",
                "message": "🤔 I'm not sure what you mean. Could you rephrase that?"
            }
        else:
            return {
                "action": "spell",
                "message": "🔤 Please spell out exactly what you want, or type 'cancel'"
            }
    
    def _build_clarification_message(self, candidates: List[Tuple[float, str, str]]) -> str:
        """Build message with numbered choices"""
        message = "🤔 I found a few options. Which one?\n"
        for i, (score, skill_id, skill_name) in enumerate(candidates, 1):
            message += f"  {i}. {skill_name} ({score:.0%} match)\n"
        message += "  0. None of these (cancel)\n"
        message += "\nType a number, or describe what you want:"
        return message
    
    # === CONTEXT MANAGEMENT ===
    
    def get_state(self) -> DialogueState:
        """Get current dialogue state"""
        return self.context.state
    
    def reset_context(self):
        """Reset conversation context"""
        self.context.reset()
    
    def can_repeat_last(self) -> bool:
        """Check if 'do it again' is possible"""
        return self.context.last_executed_skill is not None
    
    def get_last_skill(self) -> Optional[str]:
        """Get last executed skill for 'do it again' commands"""
        return self.context.last_executed_skill
    
    def mark_executed(self, skill_id: str):
        """Mark skill as executed for repeat functionality"""
        self.context.last_executed_skill = skill_id
        self.context.reset()  # Clear pending state
