"""Step 3 smoke test: open the app through Appium and count screen elements.
Run with Appium already started in another terminal:  python scripts/smoke_test.py
"""
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from appium import webdriver
from appium.options.android import UiAutomator2Options
from mcp_server.config import load_config

cfg = load_config()
print(f"Profile: {cfg['profile']}  App: {cfg['app_package']}  Device: {cfg['device_name']}")

opts = UiAutomator2Options()
opts.device_name = cfg["device_name"]
opts.app = cfg["app_path"]
opts.app_package = cfg["app_package"]
opts.app_activity = cfg["app_activity"]
opts.new_command_timeout = 120

start = time.time()
driver = webdriver.Remote(cfg["appium_url"], options=opts)
try:
    print(f"Session started in {time.time() - start:.1f}s")
    print("Current activity:", driver.current_activity)
    root = ET.fromstring(driver.page_source)
    nodes = list(root.iter())
    clickable = [n for n in nodes if n.get("clickable") == "true"]
    print(f"Elements on screen: {len(nodes)}  clickable: {len(clickable)}")
    for n in clickable[:8]:
        print("  -", n.get("class"), "|", n.get("text") or n.get("content-desc"))
    out = Path("runs") / "smoke.png"
    out.parent.mkdir(exist_ok=True)
    driver.save_screenshot(str(out))
    print("Screenshot saved:", out)
finally:
    driver.quit()
