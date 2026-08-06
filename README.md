# Voice-Controlled Android Agent

A natural-language AI agent that controls Android tablets via ADB. Speak or type commands like "open YouTube", "scroll down", "go back", or "set brightness to 50%" and the agent translates them into device actions in real time.

## Features

- **Voice Control** - hands-free mic overlay with real-time speech-to-text (Groq Whisper)
- **Text CLI** - type commands interactively in the terminal
- **Gemini Vision** - uses Google Gemini to understand what's on screen and act intelligently
- **UI Tree Navigation** - parses the Android accessibility tree for precise element targeting
- **Natural Language Intent Engine** - maps free-form speech to structured device actions
- **Device Features** - brightness, volume, Wi-Fi, Bluetooth, alarms, app launching, scrolling, typing, and more
- **Learning System** - remembers successful action sequences for faster repeat execution
- **Workflow Engine** - chain multi-step actions from a single command

## Quick Start

### Prerequisites

- Python 3.11+
- Android device/tablet connected via USB with **USB Debugging** enabled
- [ADB (Android Debug Bridge)](https://developer.android.com/tools/adb) in your PATH or use the bundled `platform-tools/`

### Installation

```bash
git clone https://github.com/chiranjivaraoatluri13/Voice-AI-agent.git
cd Voice-AI-agent
python -m venv .venv
.venv\Scripts\activate      # Windows
pip install -r requirements.txt
```

### Configuration

Copy the example env file and add your API keys:

```bash
cp .env.example .env
```

Edit `.env`:
```
GROQ_API_KEY=your_groq_api_key_here
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-3.6-flash
```

- **Groq API Key** - get one at [console.groq.com](https://console.groq.com) (used for speech-to-text)
- **Gemini API Key** - get one at [aistudio.google.com](https://aistudio.google.com) (used for vision and intent)

### Usage

**Text mode (CLI):**
```bash
python main.py
```

**Voice mode (mic overlay):**
```bash
python main.py --voice
```

### Example Commands

| Command | What it does |
|---------|-------------|
| "open youtube" | Launches the YouTube app |
| "scroll down" | Scrolls the current screen down |
| "set brightness to 70%" | Adjusts display brightness |
| "go back" | Presses the back button |
| "type hello world" | Types text into the focused field |
| "take a screenshot" | Captures the current screen |
| "turn on wifi" | Enables Wi-Fi |

## Architecture

```
main.py                     - Entry point (CLI or voice mode)
agent/
  controller.py             - Main CLI loop and command dispatcher
  intent_engine.py          - NLP intent classification and action mapping
  voice_app.py              - Voice overlay UI (tkinter + sounddevice)
  voice_stt.py              - Speech-to-text via Groq Whisper
  gemini_computer_use.py    - Gemini vision for screen understanding
  gemini_models.py          - Gemini client configuration
  screen_controller.py      - ADB-based screen interaction (tap, swipe, type)
  ui_tree_navigator.py      - Android UI hierarchy parsing
  device.py                 - Device state and feature control
  adb.py                    - Low-level ADB command wrapper
  workflow_engine.py        - Multi-step workflow execution
  learner.py                - Action learning and memory
```

## Tech Stack

- **Python 3.11+** - core runtime
- **Google Gemini (gemini-3.6-flash)** - vision and computer use
- **Groq (whisper-large-v3-turbo)** - speech-to-text
- **ADB** - Android device communication
- **Tkinter** - voice overlay GUI
- **python-dotenv** - environment configuration

## License

Personal project by [@chiranjivaraoatluri13](https://github.com/chiranjivaraoatluri13)
