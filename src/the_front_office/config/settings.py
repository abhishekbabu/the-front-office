import os
from pathlib import Path
from dotenv import load_dotenv

# Ensure .env is loaded before evaluating os.getenv
# Walk up from this file to find the project root: src/the_front_office/config -> root
project_root = Path(__file__).resolve().parents[3]
env_path = project_root / ".env"
load_dotenv(env_path)

# Gemini Settings
GEMINI_API_KEY = os.getenv("GOOGLE_API_KEY")
DEFAULT_MODEL = "gemini-2.5-pro"

# Scouting Settings
DEFAULT_FREE_AGENT_COUNT = 20
REPORT_FREE_AGENT_LIMIT = 15

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
