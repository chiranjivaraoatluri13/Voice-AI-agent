# =========================
# FILE: agent/workflow_runner.py
# =========================
"""
Stub workflow runner — provides the interface controller.py expects.
Replace with real implementation when ready.
"""

_workflows = {}


def workflow_count() -> int:
    """Return number of learned workflows."""
    return len(_workflows)


def intercept(utterance: str):
    """
    Check if utterance matches a learned workflow.
    
    Returns:
        ("pass", utterance)    — not a workflow, continue normal flow
        ("handled", None)      — workflow system handled it (e.g. 'list workflows')
        ("execute", [steps])   — replay these steps
    """
    t = utterance.strip().lower()

    # List workflows
    if t in ("list workflows", "show workflows", "my workflows"):
        if not _workflows:
            print("📚 No learned workflows yet.")
            print("   Say: 'teach me to <task>' to start recording.")
        else:
            print(f"📚 Learned Workflows ({len(_workflows)}):")
            for name, steps in _workflows.items():
                print(f"  • {name} ({len(steps)} steps)")
        return ("handled", None)

    # Check for matching workflow
    for name, steps in _workflows.items():
        if name in t or t in name:
            print(f"▶ Running workflow: {name}")
            return ("execute", list(steps))

    # Not a workflow — pass through
    return ("pass", utterance)
