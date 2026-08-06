# =========================
# FILE: main.py
# =========================
"""
Voice-Controlled Android Agent
Entry point for the application
"""

# Force UTF-8 encoding on Windows before any output
import argparse
import sys
import io

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    # Reconfigure stdout to use UTF-8 (necessary on Windows with some terminal configs)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    else:
        # Fallback for older Python versions
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Voice-Controlled Android Agent — natural language tablet control.",
    )
    parser.add_argument(
        "-v",
        "--voice",
        action="store_true",
        help="Floating mic overlay (speech + typed commands) instead of the text CLI",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args()

    print("""
    ╔═══════════════════════════════════════╗
    ║  VOICE-CONTROLLED ANDROID AGENT      ║
    ║  Natural Language Interface          ║
    ║  python main.py          text CLI    ║
    ║  python main.py --voice  mic overlay ║
    ╚═══════════════════════════════════════╝
    """)

    if args.voice:
        # Lazy: sounddevice / tkinter only needed in voice mode.
        from agent.voice_app import run_voice
        run_voice()
    else:
        from agent.controller import run_cli
        run_cli()
