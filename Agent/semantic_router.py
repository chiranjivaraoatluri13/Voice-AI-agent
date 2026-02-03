# =========================
# FILE: agent/semantic_router.py
# =========================
"""
Semantic Skill Router
Maps user input to skills using semantic understanding
"""

from typing import List, Tuple, Optional
from agent.skill import SkillMemory, Skill


class SemanticRouter:
    """
    Routes user input to appropriate skills.
    Uses semantic understanding (text similarity for now, embeddings later).
    """
    
    def __init__(self, skill_memory: SkillMemory):
        self.memory = skill_memory
    
    def route(self, user_input: str, top_k: int = 5) -> List[Tuple[float, str, str]]:
        """
        Find matching skills for user input.
        
        Args:
            user_input: User's natural language request
            top_k: Number of top matches to return
        
        Returns:
            List of (score, skill_id, skill_name) tuples, sorted by score
        """
        
        # Use skill memory's search
        matches = self.memory.search_by_text(user_input)
        
        # Return top K
        results = []
        for score, skill in matches[:top_k]:
            results.append((score, skill.skill_id, skill.name))
        
        return results
    
    def route_with_context(
        self, 
        user_input: str, 
        recent_skills: List[str] = None,
        boost_recent: float = 0.1
    ) -> List[Tuple[float, str, str]]:
        """
        Route with context awareness.
        Boost recently used skills slightly.
        """
        
        matches = self.route(user_input, top_k=10)
        
        if not recent_skills:
            return matches[:5]
        
        # Boost recent skills
        boosted = []
        for score, skill_id, skill_name in matches:
            if skill_id in recent_skills:
                score = min(1.0, score + boost_recent)
            boosted.append((score, skill_id, skill_name))
        
        # Re-sort
        boosted.sort(key=lambda x: x[0], reverse=True)
        
        return boosted[:5]
    
    def explain_match(self, user_input: str, skill_id: str) -> str:
        """
        Explain why a skill was matched.
        Useful for debugging and transparency.
        """
        skill = self.memory.get_skill(skill_id)
        if not skill:
            return "Skill not found"
        
        from difflib import SequenceMatcher
        
        user_lower = user_input.lower()
        
        best_phrase = ""
        best_score = 0.0
        
        for phrase in skill.example_phrases:
            score = SequenceMatcher(None, user_lower, phrase.lower()).ratio()
            if score > best_score:
                best_score = score
                best_phrase = phrase
        
        return f"Matched '{user_input}' to '{skill.name}' (score: {best_score:.2f}, similar to: '{best_phrase}')"


# === FUTURE: Embedding-based Router ===
# This would use sentence-transformers for semantic embeddings
# class EmbeddingRouter(SemanticRouter):
#     def __init__(self, skill_memory, model_name="all-MiniLM-L6-v2"):
#         super().__init__(skill_memory)
#         from sentence_transformers import SentenceTransformer
#         self.model = SentenceTransformer(model_name)
#         self._precompute_embeddings()
#     
#     def _precompute_embeddings(self):
#         """Compute embeddings for all skills"""
#         for skill in self.memory.list_skills():
#             # Combine example phrases
#             text = " ".join(skill.example_phrases)
#             skill.embedding = self.model.encode(text).tolist()
#     
#     def route(self, user_input, top_k=5):
#         """Use cosine similarity with embeddings"""
#         query_emb = self.model.encode(user_input)
#         # ... compute similarities ...
#         pass
