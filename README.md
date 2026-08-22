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
- **Config:** pydantic-settings (typed, validated env vars)
- **APIs:**
    - **Yahoo Fantasy Sports API** (via `yahoofantasy` SDK)
    - **Google Gemini API** (via `google-genai` SDK)
    - **NBA Data** (via `nba_api`)
- **AI Engine:** Gemini 2.5 (Pro for strategy, Flash for parsing)
- **Dev Tools:** uv (Env & Locking), Ruff (Lint & Format), Pyrefly (Typesafety), pre-commit (Enforcement)

---

## 📂 Project Structure
```text
the-front-office/
├── src/
│   └── the_front_office/
│       ├── clients/        # External API wrappers (Gemini, Yahoo, NBA)
│       ├── config/         # Configuration layer (constants, settings)
│       ├── exceptions.py   # Domain exceptions raised by services
│       ├── main.py         # Entry point & Interactive CLI
│       └── scout/          # Scout orchestrator (AI waiver analysis)
├── tests/                  # Hermetic unit tests (pytest)
├── .agent/rules/rules.md    # Project rules & Assistant guidelines
├── .env                    # Local secrets (Client IDs/Secrets)
├── pyrefly.toml            # Type checking configuration
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

# Create the venv, install locked dependencies, and install the git hooks
just install
```

<details>
<summary>Without <code>just</code></summary>

```bash
uv venv --python 3.10
uv pip install -e ".[dev]"
.venv/bin/pre-commit install
```
</details>

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
just run
# OR, if installed on PATH:
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

## 🧰 Common Tasks
```text
just              List every recipe
just check        Lint, type check and test — everything the git hooks run
just fmt          Auto-fix lint findings and format
just test         Run the hermetic test suite (add args: just test "-k scout")
just run          Start the interactive CLI
just clean        Remove caches and build artefacts
```

---

## 🔒 Security & Quality
- Never commit `.env` or `.yahoofantasy` (token) files.
- **Type Safety:** Always run `pyrefly check` before committing changes (also enforced by pre-commit).
- **Tests:** `pytest` runs the hermetic suite (no network, no credentials). Tests that hit a live API are
  marked `@pytest.mark.integration` and deselected by default; run them with `pytest -m integration`.
- **Lint & Format:** `ruff check src/ --fix` and `ruff format src/`. Both run automatically via pre-commit.
