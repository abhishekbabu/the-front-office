# 🏀 The Front Office: NBA Fantasy Intelligence

**The Front Office** is an AI-powered General Manager designed to transform raw league data into competitive advantages. It serves as a command center for scouting the waiver wire, evaluating high-stakes trades, and providing natural language insights into team performance across multiple platforms (Yahoo/ESPN).

---

## 🚀 Current Status: Mission 2 Complete
The Waiver Engine is now live! You can authenticate with Yahoo Fantasy and generate AI-powered "Morning Scout Reports" that analyze your roster against available free agents using Gemini.

---

## 🛠 Technical Stack
- **Language:** Python 3.10
- **APIs:** 
    - **Yahoo Fantasy Sports API** (via `yahoofantasy` SDK)
    - **Google Gemini API** (via `google-genai` SDK)
- **AI Engine:** Gemini 2.5 (Pro for strategy, Flash for high-speed parsing)
- **Dev Tools:** Mypy (Typesafety), Flake8 (Hygiene)

---

## 📂 Project Structure
```text
the-front-office/
├── src/
│   └── the_front_office/
│       ├── auth/           # OAuth2 Handshake (Yahoo)
│       ├── main.py         # Entry point & CLI handler
│       └── scout.py        # Waiver Engine & AI Intelligence
├── .agent/                 # Project rules & Assistant guidelines
├── .env                    # Local secrets (Client IDs/Secrets)
├── mypy.ini                # Type checking configuration
├── pyproject.toml          # Package metadata & Dependencies
└── requirements.txt        # Pinned dependencies
```

---

## 🏁 Getting Started

### 1. Prerequisites
- **Python 3.10** (required for `yahoofantasy` compatibility)
- A Yahoo Developer App (with Fantasy Sports "Read" permissions and `https://localhost:8080` as the Redirect URI).
- A Google Gemini API Key (from Google AI Studio).

### 2. Setup
```bash
# Clone the repository
git clone <repo-url>
cd the-front-office

# Create and activate virtual environment
python -m venv .venv
source .venv/Scripts/activate  # Windows: .venv\Scripts\activate

# Install dependencies (including dev tools)
pip install -e ".[dev]"
```

### 3. Configuration
Copy `.env.template` to `.env` and add your credentials:
```env
YAHOO_CLIENT_ID=your_id
YAHOO_CLIENT_SECRET=your_secret
GOOGLE_API_KEY=your_gemini_key
```

### 4. Run

#### Generate Scout Report (AI)
Analyze your team against available free agents:
```bash
python -m the_front_office.main --scout
```

#### Print Roster (Standard)
List your current NBA rosters for all leagues:
```bash
python -m the_front_office.main
```

---

## 🗺 Roadmap
- [x] **Mission 1: Connectivity** — OAuth2 & Roster Sync.
- [x] **Mission 2: The Waiver Engine** — Scan top free agents and summarize via Gemini 2.5 Pro.
- [ ] **Mission 3: Dashboard MVP** — Streamlit "Morning Scout Report."
- [ ] **Mission 4: Trade War Room** — Natural language trade evaluation.

---

## 🔒 Security & Quality
- Never commit `.env` or `.yahoofantasy` (token) files.
- **Type Safety:** Always run `mypy src/the_front_office` before committing changes.
- **Import Hygiene:** Keep code clean of unused imports (`flake8`).
