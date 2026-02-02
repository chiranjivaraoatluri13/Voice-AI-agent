# =========================
# FILE: agent/learner.py
# =========================
"""
User training system for custom command mappings.
Allows users to teach the agent shortcuts like:
  "when I say 'google', open Chrome"
  "when I say 'music', open Spotify"
"""

import json
import os
from typing import Optional, Dict, List
from datetime import datetime


class CommandLearner:
    """
    Manages user-defined command mappings and learning.
    Persists training data to a JSON file.
    """

    def __init__(self, config_path: str = "user_mappings.json") -> None:
        self.config_path = config_path
        self.mappings: Dict[str, str] = {}  # query -> package
        self.aliases: Dict[str, List[str]] = {}  # package -> list of aliases
        self.training_history: List[Dict] = []
        self.load()

    # -------------------------
    # Persistence
    # -------------------------
    def load(self) -> None:
        """Load user mappings from disk."""
        if not os.path.exists(self.config_path):
            self._initialize_default()
            return

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.mappings = data.get("mappings", {})
                self.aliases = data.get("aliases", {})
                self.training_history = data.get("history", [])
        except Exception as e:
            print(f"⚠️ Could not load mappings: {e}")
            self._initialize_default()

    def save(self) -> None:
        """Save user mappings to disk."""
        try:
            data = {
                "mappings": self.mappings,
                "aliases": self.aliases,
                "history": self.training_history,
                "last_updated": datetime.now().isoformat(),
            }
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️ Could not save mappings: {e}")

    def _initialize_default(self) -> None:
        """Create default empty mappings."""
        self.mappings = {}
        self.aliases = {}
        self.training_history = []

    # -------------------------
    # Learning Interface
    # -------------------------
    def teach(self, query: str, package: str, label: str = "") -> None:
        """
        Teach a new mapping.
        
        Args:
            query: User's shortcut/alias (e.g., "google", "music")
            package: Package name (e.g., "com.android.chrome")
            label: Human-readable app name (e.g., "Chrome")
        """
        query_key = query.strip().lower()
        
        # Store the mapping
        self.mappings[query_key] = package
        
        # Store reverse mapping (for listing what aliases point to an app)
        if package not in self.aliases:
            self.aliases[package] = []
        if query_key not in self.aliases[package]:
            self.aliases[package].append(query_key)
        
        # Log training event
        self.training_history.append({
            "timestamp": datetime.now().isoformat(),
            "query": query_key,
            "package": package,
            "label": label,
        })
        
        self.save()
        
        display_label = label if label else package
        print(f"✅ Learned: '{query}' → {display_label}")

    def forget(self, query: str) -> bool:
        """
        Remove a learned mapping.
        
        Returns:
            True if mapping was removed, False if it didn't exist
        """
        query_key = query.strip().lower()
        
        if query_key not in self.mappings:
            return False
        
        package = self.mappings[query_key]
        
        # Remove from mappings
        del self.mappings[query_key]
        
        # Remove from aliases
        if package in self.aliases:
            self.aliases[package] = [
                a for a in self.aliases[package] if a != query_key
            ]
            if not self.aliases[package]:
                del self.aliases[package]
        
        self.save()
        print(f"🗑️ Forgot: '{query}'")
        return True

    # -------------------------
    # Query Resolution
    # -------------------------
    def resolve(self, query: str) -> Optional[str]:
        """
        Check if user has taught a mapping for this query.
        
        Returns:
            Package name if mapping exists, None otherwise
        """
        query_key = query.strip().lower()
        return self.mappings.get(query_key)

    # -------------------------
    # Information Display
    # -------------------------
    def list_mappings(self) -> None:
        """Display all learned mappings."""
        if not self.mappings:
            print("📚 No custom mappings yet. Teach me some!")
            print("   Example: 'teach google chrome' (after opening Chrome)")
            return
        
        print(f"📚 Learned Mappings ({len(self.mappings)}):")
        for query, package in sorted(self.mappings.items()):
            # Get all aliases for this package
            all_aliases = self.aliases.get(package, [])
            if len(all_aliases) > 1:
                other_aliases = [a for a in all_aliases if a != query]
                alias_info = f" (also: {', '.join(other_aliases)})"
            else:
                alias_info = ""
            
            print(f"  '{query}' → {package}{alias_info}")

    def get_aliases_for(self, package: str) -> List[str]:
        """Get all user-defined aliases for a package."""
        return self.aliases.get(package, [])

    # -------------------------
    # Interactive Training
    # -------------------------
    def interactive_teach(self, query: str, package: str, label: str) -> None:
        """
        Interactive teaching flow with confirmation.
        """
        print(f"\n💡 Teaching mode:")
        print(f"   When you say: '{query}'")
        print(f"   I will open: {label} ({package})")
        
        confirm = input("   Confirm? (y/n): ").strip().lower()
        
        if confirm in ("y", "yes"):
            self.teach(query, package, label)
            print(f"✅ Got it! Next time you say '{query}', I'll open {label}.")
        else:
            print("❌ Cancelled. No mapping saved.")

    def suggest_teaching(self, query: str, chosen_package: str, chosen_label: str) -> None:
        """
        Suggest teaching after user makes a selection.
        Called after user chooses from multiple options.
        """
        # Don't suggest if already learned
        if query.strip().lower() in self.mappings:
            return
        
        print(f"\n💡 Tip: Want me to remember this?")
        print(f"   Type: teach {query}")
        print(f"   Then I'll always open {chosen_label} when you say '{query}'")
