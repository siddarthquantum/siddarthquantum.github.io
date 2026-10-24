"""Loads .env plus the active app profile (FR-01, FR-18)."""
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def load_config() -> dict:
    load_dotenv(ROOT / ".env")
    profile = os.getenv("QA_PROFILE", "apidemos")
    profile_file = ROOT / "profiles" / f"{profile}.env"
    if not profile_file.exists():
        raise FileNotFoundError(f"Profile not found: {profile_file}")
    load_dotenv(profile_file, override=True)
    return {
        "profile": profile,
        "appium_url": os.getenv("APPIUM_URL", "http://127.0.0.1:4723"),
        "device_name": os.getenv("DEVICE_NAME", "emulator-5554"),
        "app_path": os.getenv("APP_PATH", ""),
        "app_package": os.getenv("APP_PACKAGE", ""),
        "app_activity": os.getenv("APP_ACTIVITY", ""),
        "step_limit": int(os.getenv("STEP_LIMIT", "25")),
        "reset_clears_data": os.getenv("RESET_CLEAR_DATA", "true").lower() == "true",
    }
