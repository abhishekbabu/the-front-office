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

# Yahoo Settings
YAHOO_CLIENT_ID = os.getenv("YAHOO_CLIENT_ID")
YAHOO_CLIENT_SECRET = os.getenv("YAHOO_CLIENT_SECRET")
YAHOO_REDIRECT_URI = "https://localhost:8080"
YAHOO_TOKEN_FILE = ".yahoofantasy"
YAHOO_MAX_WEEKLY_ADDS = int(os.getenv("YAHOO_MAX_WEEKLY_ADDS", "3"))

# Scouting Settings
DEFAULT_FREE_AGENT_COUNT = 20
REPORT_FREE_AGENT_LIMIT = 15
NBA_API_DELAY = 4.0  # Seconds to wait between nba_api calls
NBA_CACHE_FILE = ".nba_cache.json"  # Unified cache for all NBA data (stats + schedule)

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
