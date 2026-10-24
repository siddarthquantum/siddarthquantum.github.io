"""Step 4a helper: save the raw page_source XML of the app's first screen to runs/home.xml.
Run with Appium already started:  python scripts/dump_xml.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from appium import webdriver
from appium.options.android import UiAutomator2Options
from mcp_server.config import load_config

cfg = load_config()
opts = UiAutomator2Options()
opts.device_name = cfg["device_name"]
opts.app = cfg["app_path"]
opts.app_package = cfg["app_package"]
opts.app_activity = cfg["app_activity"]

driver = webdriver.Remote(cfg["appium_url"], options=opts)
try:
    out = Path("runs") / "home.xml"
    out.parent.mkdir(exist_ok=True)
    out.write_text(driver.page_source, encoding="utf-8")
    print("Saved:", out, f"({out.stat().st_size} bytes)")
finally:
    driver.quit()
