# 🏀 The Front Office: NBA Fantasy Intelligence

**The Front Office** is an AI-powered General Manager designed to transform raw league data into competitive advantages. It serves as a command center for scouting the waiver wire, evaluating high-stakes trades, and providing natural language insights into team performance across multiple platforms (Yahoo/ESPN).

---

## 🚀 Current Status: Mission 1 Complete
The project is initialized with a modular Python structure and full Yahoo Fantasy OAuth2 connectivity. You can currently authenticate and print your NBA rosters to the terminal.

---

## 🛠 Technical Stack
- **Language:** Python 3.11+
- **APIs:** 
    - **Yahoo Fantasy Sports API** (via `yahoofantasy` SDK)
    - **ESPN Fantasy API** (planned)
    - **nba_api** (planned for real-world trends)
- **AI Engine:** Google Gemini (Flash for data parsing, Pro for complex strategy)
- **Frontend:** Streamlit (planned "War Room" dashboard)

---

## 📂 Project Structure
```text
the-front-office/
├── src/
│   └── the_front_office/
│       ├── auth/           # OAuth2 Handshake (Yahoo/ESPN)
│       ├── main.py         # Entry point & Roster Printer
│       └── ...             # Future: scout, trade_analyzer
├── pyproject.toml          # Package metadata & Dependencies
├── .env                    # Local secrets (Client IDs/Secrets)
└── pyrightconfig.json      # IDE/Language Server configuration
```

---

## 🏁 Getting Started

### 1. Prerequisites
- Python 3.11+
- A Yahoo Developer App (with Fantasy Sports "Read" permissions and `https://localhost:8080` as the Redirect URI).

### 2. Setup
```bash
# Clone the repository
git clone <repo-url>
cd the-front-office

# Create and activate virtual environment
python -m venv .venv
source .venv/Scripts/activate  # Windows Git Bash

# Install dependencies
pip install -e .
```

### 3. Configuration
Copy `.env.template` to `.env` and add your credentials:
```env
YAHOO_CLIENT_ID=your_id
YAHOO_CLIENT_SECRET=your_secret
```

### 4. Run
Print your current NBA rosters:
```bash
python -m the_front_office.main
```

---

## 🗺 Roadmap
- [x] **Mission 1: Connectivity** — OAuth2 & Roster Sync.
- [ ] **Mission 2: The Waiver Engine** — Scan top free agents and summarize "Best Value" via Gemini.
- [ ] **Mission 3: Dashboard MVP** — Streamlit "Morning Scout Report."
- [ ] **Mission 4: Trade War Room** — Natural language trade evaluation.

---

## 🔒 Security
- Never commit `.env` or `oauth2.json` to version control.
- Credentials and tokens are stored locally.
