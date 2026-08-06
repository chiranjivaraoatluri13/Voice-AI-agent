# =========================
# FILE: agent/workflow_runner.py
# =========================
"""
Workflow runner — thin adapter that wires the real WorkflowEngine into the
controller's intercept() contract.

Previously this was a stub with an always-empty in-memory dict, which meant the
advertised "teach me to <task>" feature silently did nothing. This adapter
delegates to WorkflowEngine (workflow_engine.py) so recording, matching and
replay actually work, while preserving graceful degradation: if the engine
cannot be imported, everything falls back to normal command handling.

intercept() contract expected by controller.py:
    ("pass", utterance)  — not a workflow, continue normal flow
                           (utterance may be modified, e.g. during recording)
    ("handled", None)    — fully handled here (list / delete / teach-start / done)
    ("execute", [steps]) — replay these command strings
"""

from typing import List, Tuple, Optional

try:
    from agent.workflow_engine import WorkflowEngine
    _engine: Optional["WorkflowEngine"] = WorkflowEngine()
except Exception as e:  # pragma: no cover - defensive: never break main loop
    print(f"⚠️ Workflow engine unavailable: {e}")
    _engine = None


def workflow_count() -> int:
    """Return number of learned workflows."""
    if not _engine:
        return 0
    return len(_engine.workflows)


def intercept(utterance: str) -> Tuple[str, object]:
    """Route an utterance through the workflow engine."""
    if not _engine:
        return ("pass", utterance)

    t = utterance.strip().lower()

    # --- If mid-recording, feed the input to the recorder ---
    if _engine.recording:
        passthrough = _engine.handle_recording_input(utterance)
        if passthrough is None:
            # "done" / "cancel" — handled internally, execute nothing
            return ("handled", None)
        # Record the step AND let it run normally so the user sees it happen
        return ("pass", passthrough)

    # --- Management commands ---
    if t in ("list workflows", "show workflows", "my workflows"):
        _engine.list_workflows()
        return ("handled", None)

    if t.startswith("delete workflow ") or t.startswith("forget workflow "):
        parts = utterance.split(" ", 2)
        name = parts[2].strip() if len(parts) > 2 else ""
        if name and _engine.delete_workflow(name):
            print(f"🗑️ Deleted workflow: {name}")
        else:
            print(f"❌ No workflow named '{name}'")
        return ("handled", None)

    # --- Start teaching a new workflow? ---
    description = _engine.check_teach_start(utterance)
    if description:
        _engine.start_recording(description)
        return ("handled", None)

    # --- Match an existing workflow (high threshold = safe) ---
    match = _engine.match(utterance)
    if match:
        wf, variables, score = match
        print(f"▶ Running workflow: {wf.name} ({score:.0%} match)")
        steps = _engine.prepare_steps(wf, variables)
        return ("execute", list(steps))

    # Not a workflow — pass through to normal handling
    return ("pass", utterance)
