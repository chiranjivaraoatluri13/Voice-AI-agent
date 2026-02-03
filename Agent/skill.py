# =========================
# FILE: agent/skill.py
# =========================
"""
Skill Abstraction Layer
Separates language understanding from execution
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable
import json
import os
from datetime import datetime


@dataclass
class Skill:
    """
    A Skill represents something the agent knows how to do.
    Separates MEANING (language) from PROCEDURE (execution).
    """
    
    # === MEANING LAYER (Language) ===
    skill_id: str  # Unique ID (e.g., "email.check_spam")
    name: str  # Human-readable name (e.g., "Check Junk Emails")
    description: str  # What it does
    canonical_intent: str  # Semantic intent (e.g., "email.check_spam")
    
    # Natural language variations
    example_phrases: List[str] = field(default_factory=list)
    # ["check junk emails", "see if there are spam", "look at spam folder"]
    
    # Parameters (optional)
    parameters: Dict[str, Any] = field(default_factory=dict)
    # {"app": "gmail", "timeframe": "recent", "folder": "spam"}
    
    # === PROCEDURE LAYER (Execution) ===
    procedure_type: str = "ui_sequence"  # "ui_sequence", "app_launch", "api_call"
    
    # For UI sequences
    ui_steps: List[Dict[str, Any]] = field(default_factory=list)
    # [
    #   {"action": "launch_app", "package": "com.google.android.gm"},
    #   {"action": "tap", "element": "spam_folder"},
    #   {"action": "wait", "ms": 500}
    # ]
    
    # For app launches
    target_package: Optional[str] = None
    
    # === METADATA ===
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_used: Optional[str] = None
    usage_count: int = 0
    success_rate: float = 1.0  # Track reliability
    
    # Semantic embedding (computed later)
    embedding: Optional[List[float]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for storage"""
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "canonical_intent": self.canonical_intent,
            "example_phrases": self.example_phrases,
            "parameters": self.parameters,
            "procedure_type": self.procedure_type,
            "ui_steps": self.ui_steps,
            "target_package": self.target_package,
            "created_at": self.created_at,
            "last_used": self.last_used,
            "usage_count": self.usage_count,
            "success_rate": self.success_rate,
            # Don't save embedding (recompute on load)
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Skill':
        """Deserialize from dict"""
        return cls(**data)
    
    def update_usage(self, success: bool = True):
        """Update usage statistics"""
        self.usage_count += 1
        self.last_used = datetime.now().isoformat()
        
        # Update success rate (exponential moving average)
        alpha = 0.1  # Learning rate
        new_success = 1.0 if success else 0.0
        self.success_rate = (1 - alpha) * self.success_rate + alpha * new_success


class SkillMemory:
    """
    Long-term storage of learned skills.
    Persistent storage with semantic retrieval capability.
    """
    
    def __init__(self, storage_path: str = "skill_memory.json"):
        self.storage_path = storage_path
        self.skills: Dict[str, Skill] = {}
        self.load()
    
    # === STORAGE ===
    
    def load(self) -> None:
        """Load skills from disk"""
        if not os.path.exists(self.storage_path):
            self._initialize_default_skills()
            return
        
        try:
            with open(self.storage_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for skill_data in data.get("skills", []):
                    skill = Skill.from_dict(skill_data)
                    self.skills[skill.skill_id] = skill
        except Exception as e:
            print(f"⚠️ Could not load skill memory: {e}")
            self._initialize_default_skills()
    
    def save(self) -> None:
        """Save skills to disk"""
        try:
            data = {
                "skills": [skill.to_dict() for skill in self.skills.values()],
                "last_updated": datetime.now().isoformat()
            }
            with open(self.storage_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️ Could not save skill memory: {e}")
    
    # === SKILL MANAGEMENT ===
    
    def add_skill(self, skill: Skill) -> None:
        """Add a new skill to memory"""
        self.skills[skill.skill_id] = skill
        self.save()
    
    def get_skill(self, skill_id: str) -> Optional[Skill]:
        """Get skill by ID"""
        return self.skills.get(skill_id)
    
    def remove_skill(self, skill_id: str) -> bool:
        """Remove a skill"""
        if skill_id in self.skills:
            del self.skills[skill_id]
            self.save()
            return True
        return False
    
    def list_skills(self) -> List[Skill]:
        """Get all skills"""
        return list(self.skills.values())
    
    # === RETRIEVAL ===
    
    def search_by_text(self, query: str) -> List[tuple[float, Skill]]:
        """
        Simple text-based search (no embeddings).
        Returns list of (score, skill) tuples sorted by relevance.
        """
        from difflib import SequenceMatcher
        
        query_lower = query.lower()
        scored_skills = []
        
        for skill in self.skills.values():
            max_score = 0.0
            
            # Check example phrases
            for phrase in skill.example_phrases:
                score = SequenceMatcher(None, query_lower, phrase.lower()).ratio()
                max_score = max(max_score, score)
            
            # Check name and description
            name_score = SequenceMatcher(None, query_lower, skill.name.lower()).ratio()
            desc_score = SequenceMatcher(None, query_lower, skill.description.lower()).ratio()
            
            max_score = max(max_score, name_score * 0.8, desc_score * 0.6)
            
            if max_score > 0.3:  # Minimum threshold
                scored_skills.append((max_score, skill))
        
        # Sort by score descending
        scored_skills.sort(key=lambda x: x[0], reverse=True)
        
        return scored_skills
    
    # === INITIALIZATION ===
    
    def _initialize_default_skills(self) -> None:
        """Create some default skills as examples"""
        
        # Example: Open YouTube
        youtube_skill = Skill(
            skill_id="app.open_youtube",
            name="Open YouTube",
            description="Launch the YouTube app",
            canonical_intent="app.launch.youtube",
            example_phrases=[
                "open youtube",
                "launch youtube",
                "start youtube",
                "go to youtube",
                "show me youtube"
            ],
            procedure_type="app_launch",
            target_package="com.google.android.youtube"
        )
        
        # Example: Open Gmail
        gmail_skill = Skill(
            skill_id="app.open_gmail",
            name="Open Gmail",
            description="Launch the Gmail app",
            canonical_intent="app.launch.gmail",
            example_phrases=[
                "open gmail",
                "launch gmail",
                "check email",
                "check my email",
                "open my email"
            ],
            procedure_type="app_launch",
            target_package="com.google.android.gm"
        )
        
        self.add_skill(youtube_skill)
        self.add_skill(gmail_skill)
        
        print("✅ Initialized default skills")
