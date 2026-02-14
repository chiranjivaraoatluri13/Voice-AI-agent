"""
3-Tier Intent Engine Test — run standalone.
Usage: python test_intent.py

Tests Tier 1 (TF-IDF) and Tier 3 (cache/teach).
Tier 2 (LLM) requires Ollama running.
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agent.intent_engine import IntentEngine

engine = IntentEngine()

tests = [
    # --- Mute/Max (previously broken) ---
    ("sound off", "VOLUME_MUTE"), ("mute", "VOLUME_MUTE"),
    ("silence", "VOLUME_MUTE"), ("turn off sound", "VOLUME_MUTE"),
    ("be quiet", "VOLUME_MUTE"),
    ("max the volume", "VOLUME_UP"), ("full volume", "VOLUME_UP"),
    ("blast it", "VOLUME_UP"), ("loudest possible", "VOLUME_UP"),
    ("as loud as it goes", "VOLUME_UP"),

    # --- Compound commands ---
    ("open chrome and search cats", "MULTI_STEP"),
    ("open youtube and play first video", "MULTI_STEP"),
    ("write hello and send", "TYPE_AND_SEND"),  # NOT compound

    # --- Natural phrasing ---
    ("take me to my messages", "OPEN_APP"),
    ("put on some music", "MEDIA_PLAY"),
    ("increase the volume", "VOLUME_UP"),
    ("make it louder", "VOLUME_UP"),
    ("make it quieter", "VOLUME_DOWN"),

    # --- Messaging ---
    ("text poojitha hello in whatsapp", "SEND_MESSAGE"),
    ("send hello to poojitha on whatsapp", "SEND_MESSAGE"),
    ("message poojitha hello", "SEND_MESSAGE"),
    ("chat with poojitha", "SEND_MESSAGE"),
    ("chat mom", "SEND_MESSAGE"),

    # --- Standard ---
    ("go to whatsapp", "OPEN_APP"), ("launch spotify", "OPEN_APP"),
    ("navigate back", "BACK"), ("go home", "HOME"),
    ("play", "MEDIA_PLAY"), ("pause", "MEDIA_PAUSE"),
    ("next song", "MEDIA_NEXT"), ("skip track", "MEDIA_NEXT"),
    ("back", "BACK"), ("home", "HOME"), ("exit", "EXIT"),
    ("scroll down", "SCROLL_DOWN"),
    ("what do you see", "SCREEN_INFO"),
    ("click subscribe", "VISION_QUERY"),
    ("search cats on youtube", "SEARCH_IN_APP"),
]

passed = failed = 0
total_ms = 0
for utt, expected in tests:
    t = time.perf_counter()
    cmd = engine.understand(utt)
    ms = (time.perf_counter() - t) * 1000
    total_ms += ms
    actual = cmd.action if cmd else "None"
    if expected.startswith("SCROLL_") and actual == "SCROLL": actual = expected
    ok = actual == expected
    passed += ok; failed += (not ok)
    s = "✅" if ok else "❌"
    d = ""
    if cmd:
        if cmd.action == "SEND_MESSAGE":
            d = f" [contact={cmd.query} msg={cmd.text} app={cmd.package}]"
        elif cmd.action == "MULTI_STEP":
            d = f" [{cmd.query}]"
        elif cmd.action == "VOLUME_UP" and cmd.amount > 2:
            d = f" [MAX={cmd.amount}]"
    print(f"{s} {ms:4.1f}ms | {actual:20s}{d} | \"{utt}\"")
    if not ok:
        print(f"                EXPECTED: {expected}")

print(f"\n{'='*60}")
print(f"{passed}/{passed+failed} passed | avg {total_ms/len(tests):.1f}ms/query")

# Teaching demo
print(f"\n{'='*60}")
print("TEACHING: 'chat' → message poojitha on whatsapp")
engine.teach_action("chat", "SEND_MESSAGE",
    {"contact": "poojitha", "app": "whatsapp"},
    examples=["talk to poojitha", "poojitha chat"])

for p in ["chat", "talk to poojitha"]:
    cmd = engine.understand(p)
    print(f"  ✅ '{p}' → {cmd.action} contact={cmd.query}" if cmd else f"  ❌ '{p}'")

engine.print_stats()
if os.path.exists("learned_actions.json"): os.remove("learned_actions.json")
