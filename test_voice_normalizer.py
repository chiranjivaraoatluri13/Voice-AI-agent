"""
Checks for the speech normalizer (agent/voice_normalizer.py).

Run: python test_voice_normalizer.py

Covers the three jobs it has to get right: fixing what Whisper misheard,
rejecting what wasn't a command, and leaving ordinary phrasing alone.
"""

from agent.voice_normalizer import SpeechNormalizer

# The labels this test's virtual tablet has installed.
INSTALLED_APPS = [
    "YouTube", "Chrome", "Gmail", "WhatsApp Business", "LinkedIn", "Settings",
    "Spotify", "ChatGPT", "Perplexity", "Coursera", "Gallery", "Camera",
    "Calculator", "Google Play Store", "Samsung Internet", "Temu", "Pinterest",
    "Maps", "Messages", "Clock", "Canvas", "Lufthansa",
]

normalizer = SpeechNormalizer(app_vocabulary=lambda: INSTALLED_APPS)

# (spoken transcript, expected normalized command)
CORRECTIONS = [
    # Homophones that change the action
    ("school down",                     "scroll down"),
    ("School down.",                    "scroll down"),
    ("stroll up a bit",                 "scroll up a bit"),
    ("wipe left",                       "swipe left"),
    ("turn of the wifi",                "turn off the wifi"),
    ("turn of bluetooth",               "turn off bluetooth"),
    # Spacing and spelling of device vocabulary
    ("turn on blue tooth",              "turn on bluetooth"),
    ("enable wi fi",                    "enable wifi"),
    ("switch on the flash light",       "switch on the flashlight"),
    ("take a screen shot",              "take a screenshot"),
    ("turn on air plane mode",          "turn on airplane mode"),
    ("increase the volumn",             "increase the volume"),
    # App names
    ("open you tube",                   "open youtube"),
    ("open u tube",                     "open youtube"),
    ("open g mail",                     "open gmail"),
    ("open chat gpt",                   "open chatgpt"),
    ("search cats on you tube",         "search cats on youtube"),
    ("open linked in",                  "open linkedin"),
    # Fuzzy match against the installed list
    ("open sportify",                   "open Spotify"),
    ("open perplex city",               "open perplexity"),
    ("open lufthansa airlines",         "open Lufthansa"),
    ("open corsera",                    "open coursera"),
    # Tap-context only
    ("click describe",                  "click subscribe"),
    # Fillers, wake words, politeness, stutter
    ("um, open youtube please",         "open youtube"),
    ("hey agent, go home",              "go home"),
    ("okay so scroll down",             "scroll down"),
    ("open open youtube",               "open youtube"),
    ("scroll down, thanks",             "scroll down"),
    # Spoken numbers in numeric contexts
    ("set the volume to fifty",         "set the volume to 50"),
    ("set brightness to twenty five percent", "set brightness to 25 percent"),
]

# Must survive untouched — over-correction is worse than no correction.
UNTOUCHED = [
    "search for school on youtube",
    "what do you see on screen",
    "describe the screen",
    "click the like button",
    "open a new tab",
    "type hello world and send",
    "play three body problem",
    "teach me to check my email",
]

# Should never reach the intent engine.
REJECTED = [
    "Thanks for watching!",
    "Thank you.",
    "[BLANK_AUDIO]",
    "(upbeat music)",
    "you",
    "uh",
    "okay",
    "",
    ".",
    "Subtitles by the Amara.org community",
]


def main() -> int:
    failures = []

    for spoken, expected in CORRECTIONS:
        result = normalizer.normalize(spoken)
        if not result.accepted:
            failures.append(f"REJECTED  {spoken!r} (reason: {result.reason})")
        elif result.text.lower() != expected.lower():
            failures.append(f"CORRECT   {spoken!r} → {result.text!r}, expected {expected!r}")

    for spoken in UNTOUCHED:
        result = normalizer.normalize(spoken)
        if not result.accepted:
            failures.append(f"REJECTED  {spoken!r} (reason: {result.reason})")
        elif result.text.lower() != spoken.lower():
            failures.append(f"MUTATED   {spoken!r} → {result.text!r}")

    for spoken in REJECTED:
        result = normalizer.normalize(spoken)
        if result.accepted:
            failures.append(f"ACCEPTED  {spoken!r} → {result.text!r} (should be ignored)")

    total = len(CORRECTIONS) + len(UNTOUCHED) + len(REJECTED)
    if failures:
        print(f"{len(failures)} of {total} checks failed:\n")
        for line in failures:
            print("  " + line)
        return 1

    print(f"All {total} speech-normalizer checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
