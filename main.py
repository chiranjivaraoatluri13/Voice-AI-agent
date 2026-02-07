# =========================
# FILE: main.py
# =========================
"""
Voice-Controlled Android Agent
Entry point for the application
"""

from agent.controller import run_cli

if __name__ == "__main__":
    print("""
    ╔═══════════════════════════════════════╗
    ║  VOICE-CONTROLLED ANDROID AGENT      ║
    ║  Natural Language Interface          ║
    ╚═══════════════════════════════════════╝
    """)
    
    run_cli()
