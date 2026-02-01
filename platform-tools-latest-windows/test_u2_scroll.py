import uiautomator2 as u2
import time

# If you ever have multiple devices, you can connect by serial:
# d = u2.connect("R9TXA0CJJBW")
d = u2.connect()

print("Connected device info:", d.info)

print("Turning screen on and waiting...")
d.screen_on()
time.sleep(1)

print("Trying to find a scrollable container and scroll DOWN...")
s = d(scrollable=True)
print("Scrollable exists:", s.exists)

if not s.exists:
    print("No scrollable container detected on this screen.")
    print("Open Settings -> Apps (long list), then run again.")
    raise SystemExit(1)

# Try a few scroll actions
for i in range(3):
    print("scroll forward", i + 1)
    s.scroll.forward()
    time.sleep(1)

print("Now scroll UP...")
for i in range(2):
    print("scroll backward", i + 1)
    s.scroll.backward()
    time.sleep(1)

print("DONE.")
