"""Environment and dependency verification script for FinTalk.

Checks that required packages can be imported and verifies that environment
variables can be loaded safely without exposing secret values.
"""

import importlib
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load variables from .env if present
env_path = Path(".env")
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
    print("Found .env file and loaded environment variables.\n")
else:
    print("No .env file found yet. (Copy .env.example to .env when ready).\n")

# List of required packages to verify
PACKAGES = [
    ("fastapi", "FastAPI (Mock Banking API)"),
    ("uvicorn", "Uvicorn (ASGI Server)"),
    ("pydantic", "Pydantic (Data Validation)"),
    ("httpx", "HTTPX (HTTP Client)"),
    ("dotenv", "python-dotenv (Environment Management)"),
    ("pytest", "Pytest (Automated Testing)"),
    ("pipecat", "Pipecat (Voice AI Pipeline)"),
]

print("=== Checking Package Imports ===")
all_packages_ok = True
for package_name, description in PACKAGES:
    try:
        importlib.import_module(package_name)
        print(f"  [OK] {package_name:12} - {description}")
    except ImportError as e:
        all_packages_ok = False
        print(f"  [FAIL] {package_name:10} - MISSING ({e})")

print("\n=== Checking Environment Variables (Safe Verification) ===")
# Keys required for voice pipeline and backend
ENV_KEYS = [
    ("OPENAI_API_KEY", "Required for LLM tool calling"),
    ("DEEPGRAM_API_KEY", "Required for Speech-to-Text"),
    ("CARTESIA_API_KEY", "Required for Text-to-Speech"),
    ("DAILY_API_KEY", "Required for WebRTC Audio Transport"),
    ("BANK_API_BASE_URL", "Backend API endpoint (default: http://127.0.0.1:8000)"),
]

for key, purpose in ENV_KEYS:
    val = os.getenv(key)
    if val and val.strip() and not val.startswith("your_"):
        # Safe display: mask secret, only confirm presence
        print(f"  [CONFIGURED]     {key:20} ({purpose})")
    else:
        print(f"  [NOT CONFIGURED] {key:20} ({purpose})")

print("\n=== Summary ===")
if all_packages_ok:
    print("All core dependencies are installed and importable.")
else:
    print("Some dependencies are missing. Run: pip install -r requirements.txt")
