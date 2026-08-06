# LinkedIn Post: Portrait Scroll-Down Fix

**Status:** Ready to paste into LinkedIn  
**Tone:** Balanced — story + technical highlights  
**Credit:** Claude Opus in Cursor (AI pair programming)

---

## Main Post (copy everything below the line)

---

I've been building a voice-controlled Android agent for a tablet — say "scroll down" and the device should move.

In portrait mode, it didn't. Scroll up worked. Scroll down didn't.

Same device. Same command. Opposite results.

The agent turns natural language into ADB gestures (`input swipe`). For scrolling, it computes start/end coordinates from the current screen size and sends the swipe to the tablet.

My first instinct was rotation math — Android's `wm size` doesn't always match the coordinate space touch events actually use when the display rotates.

But the real clue was directional: up worked, down didn't. That usually means the gesture is firing — just landing in the wrong place.

I paired with Claude Opus in Cursor and debugged on a live tablet:

• `wm size` and `user_rotation` said portrait (1200×1920)
• `dumpsys display` reported the effective touch space as 1920×1200 — a landscape-locked app on a vertically held tablet
• The UI tree showed the scrollable area ended around y=1116
• Our scroll-down swipe was starting near y=1632 — below the content that could scroll

The command ran. The tablet ignored it.

Fix:
1. Read the authoritative display size from `dumpsys display` (`mOverrideDisplayInfo`)
2. Cache it briefly (~150ms once per scroll, then fast)
3. Keep slow UI hierarchy dumps off the scroll hot path

Before: scroll-down from the wrong Y, 2+ second delays.
After: correct coordinates, scroll down works in portrait, back to millisecond-range swipes.

Lesson: when automating Android, you're not fighting Python — you're fighting coordinate spaces. AI pair programming is strongest when it's grounded in real device output, not guesses.

Building voice or accessibility agents on Android? I'd love to hear how you handle orientation edge cases.

#Android #VoiceUI #AI #Cursor #BuildInPublic

---

## First Comment (optional — post immediately after)

Paste this as the first comment to add a visual without cluttering the main post:

```
Quick diagram of what was happening:

  Tablet held vertically          App forced landscape (e.g. video)
  ┌──────────────┐                ┌────────────────────────────┐
  │              │                │  scrollable region         │
  │   portrait   │     but        │  y = 53 ───────── 1116     │
  │   assumed    │  ───────►      │                            │
  │   1200×1920  │                │  scroll DOWN started here  │
  │              │                │              y ≈ 1632 ✗    │
  └──────────────┘                └────────────────────────────┘

After fix: read effective size from dumpsys display → swipe lands inside the scrollable region.
```

---

## Proof: Before vs After (for comments or DMs if asked)

| Metric | Before (broken) | After (fixed) |
|--------|-----------------|---------------|
| Assumed display size | 1200×1920 (portrait) | 1920×1200 (effective / app orientation) |
| Scroll-down start Y | ~1632 (outside scrollable area) | ~900 (inside scrollable area) |
| Scroll latency | 2+ seconds (UI dump on hot path) | ~150ms refresh, then milliseconds |
| Scroll-up | Worked (started inside region) | Still works |
| Source of truth | `wm size` + `user_rotation` | `dumpsys display` → `mOverrideDisplayInfo` |

Verified on device during debugging (YouTube landscape-locked, tablet held vertically):
- Wrong swipe: (600, 1632) → (600, 288)
- Fixed swipe: (960, 900) → (960, 300)
- Scrollable UI bounds: [0, 53][1920, 1116]

---

## Publishing Checklist

- [ ] Copy the **Main Post** section above (between the `---` markers)
- [ ] Post to LinkedIn
- [ ] Add the **First Comment** diagram (optional but recommended)
- [ ] Engage with replies — technical questions can point to coordinate-space debugging

**Note:** Hashtags trimmed to 5 per plan (#Android #VoiceUI #AI #Cursor #BuildInPublic).

---

## Talking Points if Commenters Ask

**What is the project?**  
A voice-controlled Android tablet agent — natural language in, ADB gestures out (tap, scroll, open apps).

**Why did scroll up work but not down?**  
Swipe Y positions are asymmetric (15%/85% margins). With wrong screen height, scroll-down started below the scrollable UI region; scroll-up still landed inside it.

**Why not just use `wm size`?**  
`wm size` reports the panel's natural size. Android also has an effective display size (`mOverrideDisplayInfo` in `dumpsys display`) that reflects rotation and app-forced orientation — that's what touch coordinates follow.

**What did Opus actually do?**  
Traced the scroll hot path, ran live ADB forensics on the connected tablet, compared OS-reported sizes vs code assumptions, identified the coordinate mismatch, and implemented `screen_size()` to read the authoritative display size with caching.

**Files changed:**  
`Agent/device.py` (effective display size), `Agent/controller.py` (fast scroll path, no UI dump on scroll)
