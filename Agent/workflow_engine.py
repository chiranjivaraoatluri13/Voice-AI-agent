# =========================
# FILE: agent/workflow_engine.py
# =========================
"""
Workflow Learning Engine — self-contained, zero disruption to existing commands.

SAFE DESIGN:
  - Only activates on VERY specific phrases ("I'm teaching you to X")
  - Match threshold is HIGH (0.70) so normal commands never get intercepted
  - Workflow match is checked BEFORE planner, but only if workflows exist
  - All state lives in workflows.json — no shared state with other systems
  - If workflow_engine.py doesn't exist or import fails, everything else works fine

USER INTERFACE:
  Start:  "I'm teaching you to <task>"  /  "teach me to <task>"
  Stop:   "done"  /  "done teaching"  /  "that's it"
  Cancel: "cancel"  /  "cancel teaching"
  List:   "list workflows"  /  "my workflows"
  Delete: "delete workflow <name>"  /  "forget workflow <name>"
"""

import json
import os
import re
from typing import Optional, Dict, List, Tuple
from datetime import datetime
from difflib import SequenceMatcher


# ===========================================================
# DATA
# ===========================================================
class Workflow:
    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self.steps: List[Dict] = []
        self.variables: List[str] = []
        self.trigger_phrases: List[str] = []
        self.created_at: str = datetime.now().isoformat()
        self.use_count: int = 0

    def to_dict(self) -> dict:
        return {
            "name": self.name, "description": self.description,
            "steps": self.steps, "variables": self.variables,
            "trigger_phrases": self.trigger_phrases,
            "created_at": self.created_at, "use_count": self.use_count,
        }

    @staticmethod
    def from_dict(d: dict) -> "Workflow":
        wf = Workflow(d["name"], d.get("description", ""))
        wf.steps = d.get("steps", [])
        wf.variables = d.get("variables", [])
        wf.trigger_phrases = d.get("trigger_phrases", [])
        wf.created_at = d.get("created_at", "")
        wf.use_count = d.get("use_count", 0)
        return wf


# ===========================================================
# ENGINE
# ===========================================================
class WorkflowEngine:
    """Self-contained workflow system. Does NOT touch planner, schema, or controller logic."""

    # Steps starting with these → the rest is a variable
    VARIABLE_PREFIXES = ("type ", "write ", "search ", "enter ", "input ")

    # ONLY these very specific phrases start teaching — won't collide with anything
    TEACH_PATTERNS = [
        r"i'?m\s+teaching\s+you\s+(?:to\s+|how\s+to\s+)?(.+)",
        r"teach\s+me\s+(?:to|how\s+to)\s+(.+)",
        r"let\s+me\s+(?:teach|show)\s+you\s+(?:to\s+|how\s+to\s+)?(.+)",
        r"i\s+(?:want\s+to\s+|wanna\s+)?teach\s+you\s+(?:to\s+|how\s+to\s+)?(.+)",
    ]

    # These end teaching
    DONE_PHRASES = frozenset({
        "done", "done teaching", "finished", "that's it", "thats it",
        "save", "stop teaching", "finish", "end teaching",
        "ok done", "save it", "remember that", "that is it",
    })

    # These cancel teaching
    CANCEL_PHRASES = frozenset({
        "cancel", "cancel teaching", "nevermind", "never mind", "abort", "discard",
    })

    # Synonym groups for auto-trigger generation
    VERB_SYNONYMS = {
        "play": ["watch", "view", "start"],
        "search": ["look for", "find", "look up", "google"],
        "open": ["launch", "go to", "switch to"],
        "send": ["message", "text"],
        "call": ["ring", "dial", "phone"],
        "take": ["capture", "snap"],
    }

    def __init__(self, store_path: str = "workflows.json"):
        self.store_path = store_path
        self.workflows: Dict[str, Workflow] = {}
        self.recording = False
        self._wf: Optional[Workflow] = None
        self._steps: List[str] = []
        self.load()

    # ─── PERSISTENCE ──────────────────────────────────────
    def load(self) -> None:
        if not os.path.exists(self.store_path):
            return
        try:
            with open(self.store_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for name, d in data.get("workflows", {}).items():
                self.workflows[name] = Workflow.from_dict(d)
        except Exception as e:
            print(f"⚠️ Workflow load failed: {e}")

    def save(self) -> None:
        try:
            with open(self.store_path, "w", encoding="utf-8") as f:
                json.dump(
                    {"workflows": {n: w.to_dict() for n, w in self.workflows.items()},
                     "saved_at": datetime.now().isoformat()},
                    f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️ Workflow save failed: {e}")

    # ─── DETECT TEACH START ───────────────────────────────
    def check_teach_start(self, utterance: str) -> Optional[str]:
        """Returns task description if user is starting to teach, else None."""
        t = utterance.strip().lower()
        for pattern in self.TEACH_PATTERNS:
            m = re.match(pattern, t)
            if m:
                return m.group(1).strip()
        return None

    # ─── RECORDING ────────────────────────────────────────
    def start_recording(self, description: str) -> None:
        self.recording = True
        self._steps = []
        name = self._clean_name(description)
        self._wf = Workflow(name=name, description=description)
        print(f"\n🎓 OK! Show me how to: \"{name}\"")
        print(f"   Do the steps. Say \"done\" when finished.\n")

    def handle_recording_input(self, utterance: str) -> Optional[str]:
        """
        Process input during recording.
        
        Returns:
            str  → pass this command through to execute normally
            None → handled internally (done/cancel), don't execute anything
        """
        if not self.recording:
            return utterance

        t = utterance.strip().lower()

        if t in self.DONE_PHRASES:
            self._finish()
            return None
        if t in self.CANCEL_PHRASES:
            print("   ❌ Teaching cancelled.\n")
            self.recording = False
            self._wf = None
            self._steps = []
            return None

        # Record and pass through
        n = len(self._steps) + 1
        self._steps.append(utterance.strip())
        print(f"   📝 Step {n}: {utterance.strip()}")
        return utterance.strip()

    def _finish(self) -> None:
        """Analyze steps, detect variables, save."""
        if not self._steps:
            print("   ❌ No steps recorded.\n")
            self.recording = False
            self._wf = None
            return

        wf = self._wf
        var_i = 0

        for raw in self._steps:
            is_var, var_name, template = self._detect_variable(raw, var_i)
            if is_var:
                var_i += 1
                wf.variables.append(var_name)
                wf.steps.append({"command": template, "is_variable": True,
                                 "var_name": var_name, "example": raw})
            else:
                wf.steps.append({"command": raw, "is_variable": False,
                                 "var_name": "", "example": ""})

        wf.trigger_phrases = self._make_triggers(wf)
        self.workflows[wf.name] = wf
        self.save()

        print(f"\n   ✅ Learned: \"{wf.name}\"")
        for i, s in enumerate(wf.steps, 1):
            tag = "  ← variable" if s["is_variable"] else ""
            print(f"      {i}. {s['command']}{tag}")
        if wf.variables:
            print(f"   Variables: {', '.join(wf.variables)}")
        print()

        self.recording = False
        self._wf = None
        self._steps = []

    # ─── VARIABLE DETECTION ───────────────────────────────
    def _detect_variable(self, step: str, idx: int) -> Tuple[bool, str, str]:
        """Auto-detect variable in a step. Returns (is_var, name, template)."""
        t = step.lower().strip()
        for prefix in self.VARIABLE_PREFIXES:
            if t.startswith(prefix):
                content = step[len(prefix):].strip()
                if content:
                    name = self._infer_var_name(prefix.strip(), idx)
                    return True, name, f"{prefix.strip()} {{{name}}}"
        return False, "", step

    def _infer_var_name(self, action: str, idx: int) -> str:
        """Infer variable name from action and workflow context."""
        if self._wf:
            desc = self._wf.description.lower()
            if any(w in desc for w in ("message", "text", "chat", "whatsapp", "send")):
                return "message" if idx == 0 else f"message_{idx+1}"
            if any(w in desc for w in ("search", "find", "look", "google")):
                return "query" if idx == 0 else f"query_{idx+1}"
            if any(w in desc for w in ("name", "contact", "person", "call")):
                return "name" if idx == 0 else f"name_{idx+1}"
            if any(w in desc for w in ("url", "link", "website", "address")):
                return "url" if idx == 0 else f"url_{idx+1}"
            if any(w in desc for w in ("play", "video", "song", "watch")):
                return "title" if idx == 0 else f"title_{idx+1}"
        names = ["query", "text", "input", "value"]
        return names[idx] if idx < len(names) else f"input_{idx+1}"

    # ─── TRIGGER GENERATION ───────────────────────────────
    def _make_triggers(self, wf: Workflow) -> List[str]:
        base = wf.name.lower().strip()
        triggers = {base}

        # Without articles
        loose = re.sub(r'\b(a|an|the|some|something|anything|particular|specific)\b', '', base)
        loose = re.sub(r'\s+', ' ', loose).strip()
        if loose and loose != base:
            triggers.add(loose)

        # Verb synonyms
        for verb, syns in self.VERB_SYNONYMS.items():
            if verb in base:
                for s in syns:
                    triggers.add(base.replace(verb, s, 1))

        return list(triggers)

    def _clean_name(self, desc: str) -> str:
        n = desc.lower().strip()
        for pref in ["please ", "can you ", "could you ", "i want to ", "i need to ",
                     "how to ", "how do i ", "i wanna "]:
            n = n.replace(pref, "")
        return n.strip()

    # ─── MATCHING (HIGH THRESHOLD = SAFE) ─────────────────
    def match(self, utterance: str) -> Optional[Tuple[Workflow, Dict[str, str], float]]:
        """
        Match user input against learned workflows.
        
        SAFETY: threshold is 0.70 — only matches when it's very clearly
        the same intent. Normal commands like "open youtube" will NOT
        accidentally match a workflow unless the user specifically taught one.
        """
        if not self.workflows:
            return None

        query = utterance.strip().lower()
        best_wf, best_score, best_vars = None, 0.0, {}

        for wf in self.workflows.values():
            score, variables = self._score(query, wf)
            if score > best_score:
                best_score = score
                best_wf = wf
                best_vars = variables

        # HIGH threshold — only match when confident
        if best_wf and best_score >= 0.70:
            return (best_wf, best_vars, best_score)
        return None

    def _score(self, query: str, wf: Workflow) -> Tuple[float, Dict[str, str]]:
        best, best_v = 0.0, {}
        for trigger in wf.trigger_phrases:
            if wf.variables:
                s, v = self._match_with_vars(query, trigger, wf)
            else:
                s, v = self._sim(query, trigger), {}
            if s > best:
                best, best_v = s, v
        # Also vs name
        if wf.variables:
            s, v = self._match_with_vars(query, wf.name, wf)
        else:
            s, v = self._sim(query, wf.name), {}
        if s > best:
            best, best_v = s, v
        return best, best_v

    def _sim(self, a: str, b: str) -> float:
        seq = SequenceMatcher(None, a, b).ratio()
        noise = {"a", "an", "the", "to", "on", "in", "for", "of", "my", "me", "some"}
        wa = set(a.split()) - noise
        wb = set(b.split()) - noise
        overlap = len(wa & wb) / max(len(wa), len(wb)) if wa and wb else 0
        return seq * 0.35 + overlap * 0.65

    def _match_with_vars(self, query: str, trigger: str, wf: Workflow
                          ) -> Tuple[float, Dict[str, str]]:
        """Extract variable values by matching skeleton words."""
        skeleton = self._skeleton(wf)
        if not skeleton:
            return self._sim(query, trigger), {}

        q_words = query.split()
        matched, remaining = 0, list(q_words)
        for sw in skeleton:
            for i, qw in enumerate(remaining):
                if qw == sw:
                    remaining.pop(i)
                    matched += 1
                    break

        noise = {"a", "an", "the", "to", "on", "in", "for", "of", "please", "some"}
        remaining = [w for w in remaining if w not in noise]

        if matched < len(skeleton) * 0.6:
            return self._sim(query, trigger) * 0.6, {}

        score = matched / len(skeleton)
        variables = {}
        if remaining and wf.variables:
            remaining_text = " ".join(remaining)
            if len(wf.variables) == 1:
                variables[wf.variables[0]] = remaining_text
            else:
                parts = remaining_text.split(" and ")
                for i, var in enumerate(wf.variables):
                    variables[var] = parts[i].strip() if i < len(parts) else ""
        
        return min(score * 0.9, 0.98), variables

    def _skeleton(self, wf: Workflow) -> List[str]:
        """Fixed words in workflow name (everything except variable placeholders)."""
        name_words = wf.name.lower().split()
        placeholders = {"something", "anything", "someone", "somebody", "particular",
                       "specific", "certain", "stuff", "things", "it", "that", "this",
                       "a", "an", "the", "some", "any", "my"}
        example_words = set()
        for step in wf.steps:
            if step.get("is_variable") and step.get("example"):
                for pfx in self.VARIABLE_PREFIXES:
                    if step["example"].lower().startswith(pfx):
                        example_words.update(step["example"][len(pfx):].lower().split())
        return [w for w in name_words if w not in placeholders and w not in example_words]

    # ─── REPLAY ───────────────────────────────────────────
    def prepare_steps(self, wf: Workflow, variables: Dict[str, str]) -> List[str]:
        """Substitute variables into steps. Ask user for any missing ones."""
        commands = []
        for step in wf.steps:
            cmd = step["command"]
            if step.get("is_variable"):
                var = step.get("var_name", "")
                if var in variables and variables[var]:
                    cmd = cmd.replace(f"{{{var}}}", variables[var])
                else:
                    val = input(f"   📝 What {var}? ").strip()
                    cmd = cmd.replace(f"{{{var}}}", val)
                    variables[var] = val
            commands.append(cmd)
        wf.use_count += 1
        self.save()
        return commands

    # ─── MANAGEMENT ───────────────────────────────────────
    def list_workflows(self) -> None:
        if not self.workflows:
            print("\n📚 No workflows learned yet.")
            print("   Say: \"teach me to <something>\" to start.\n")
            return
        print(f"\n📚 Workflows ({len(self.workflows)}):\n")
        for wf in sorted(self.workflows.values(), key=lambda w: w.use_count, reverse=True):
            used = f" (used {wf.use_count}x)" if wf.use_count else ""
            print(f"  📌 {wf.name}{used}")
            for i, s in enumerate(wf.steps, 1):
                tag = " ← variable" if s.get("is_variable") else ""
                print(f"      {i}. {s['command']}{tag}")
            print()

    def delete_workflow(self, name: str) -> bool:
        key = name.strip().lower()
        if key in self.workflows:
            del self.workflows[key]
            self.save()
            return True
        for k in list(self.workflows.keys()):
            if key in k or k in key:
                del self.workflows[k]
                self.save()
                return True
        return False
