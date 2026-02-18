# 🏀 The Front Office: NBA Fantasy Intelligence

**The Front Office** is an AI-powered General Manager designed to transform raw league data into competitive advantages. It serves as a command center for scouting the waiver wire, evaluating high-stakes trades, and providing natural language insights into team performance across multiple platforms (Yahoo/ESPN).

---

## 🚀 Current Status: Interactive CLI Mode (v0.1.0)
The Front Office now operates as an interactive shell for real-time fantasy management.
- **Scout Report**: Automated waiver wire analysis powered by Gemini 2.5 Pro.
- **Trade War Room**: Analyze trades with Shutdown Risk, Roster Awareness, and Live Search.
- **Roster & Matchup Views**: Quickly inspect your team, opponents, and current matchup stats.
- **Modular Architecture**: Clean separation of concerns (Config, AI, Providers).

---

## 🛠 Technical Stack
- **Language:** Python 3.10
- **APIs:** 
    - **Yahoo Fantasy Sports API** (via `yahoofantasy` SDK)
    - **Google Gemini API** (via `google-genai` SDK)
    - **NBA Data** (via `nba_api`)
- **AI Engine:** Gemini 2.5 (Pro for strategy, Flash for parsing)
- **Dev Tools:** Mypy (Typesafety), Flake8 (Hygiene)

---

## 📂 Project Structure
```text
the-front-office/
├── src/
│   └── the_front_office/
│       ├── clients/        # External API wrappers (Gemini, Yahoo, NBA)
│       ├── config/         # Configuration layer (constants, settings)
│       ├── main.py         # Entry point & Interactive CLI
│       └── scout/          # Scout orchestrator (AI waiver analysis)
├── .agent/rules/rules.md    # Project rules & Assistant guidelines
├── .env                    # Local secrets (Client IDs/Secrets)
├── mypy.ini                # Type checking configuration
└── pyproject.toml          # Package metadata & Dependencies
```

---

## 🏁 Getting Started

### 1. Prerequisites
- **Python 3.10**
- A Yahoo Developer App (with Fantasy Sports "Read" permissions and `https://localhost:8080` as the Redirect URI).
- A Google Gemini API Key (from Google AI Studio).

### 2. Setup
```bash
# Clone the repository
git clone <repo-url>
cd the-front-office

# Create and activate virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Mac/Linux:
source .venv/bin/activate

# Install dependencies (editable mode)
pip install -e ".[dev]"
```

### 3. Configuration
Copy `.env.template` to `.env` and configure your credentials:
```env
# Required
YAHOO_CLIENT_ID=your_id
YAHOO_CLIENT_SECRET=your_secret
GOOGLE_API_KEY=your_gemini_key

# Optional (Defaults shown)
YAHOO_MAX_WEEKLY_ADDS=3
LOG_LEVEL=INFO
```

### 4. Run (Interactive Mode)
Start the CLI application. You will be prompted to authenticate with Yahoo on the first run.
```bash
python -m the_front_office.main
# OR if installed via pip:
front-office
```

Once inside the shell, use the following commands:
- **/scout**: Run the AI-powered waiver wire analysis (Morning Scout Report).
- **/scout --mock**: Test the scout report with mock data (saves API tokens).
- **/rosters**: View all rosters in your league.
- **/my-roster**: View your specific team roster.
- **/trade <txt>**: Evaluate a trade (natural language).
- **/trade --mock <txt>**: Evaluate a trade with mock data.
- **/help**: List all available commands.
- **/quit**: Exit the application.

---

## 🗺 Roadmap
- [x] **Mission 1: Connectivity** — OAuth2 & Roster Sync.
- [x] **Mission 2: The Waiver Engine** — Scan top free agents and summarize via Gemini 2.5 Pro with **Matchup Context**.
- [x] **Mission 3: Interactive CLI** — Robust command loop for easy navigation.
- [x] **Mission 4: Trade War Room** — Natural language trade evaluation (Shutdown Risk, Roster Awareness, Live Search).
- [ ] **Mission 5: Dashboard MVP** — Web-based "Morning Scout Report" (Streamlit/React).

---

## 🔒 Security & Quality
- Never commit `.env` or `.yahoofantasy` (token) files.
- **Type Safety:** Always run `mypy src/the_front_office` before committing changes.
- **Import Hygiene:** Keep code clean of unused imports (`flake8`).
