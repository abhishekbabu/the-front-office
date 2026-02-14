# Project "The Front Office": All-In-One NBA Fantasy Intelligence

## 1. Project Vision
An all-encompassing NBA Fantasy command center that transforms raw league data into competitive advantages. **The Front Office** serves as an AI-powered General Manager, capable of scouting the waiver wire, evaluating high-stakes trades, and providing natural language insights into team performance across multiple platforms (Yahoo/ESPN).

---

## 2. Technical Stack
* **IDE:** Antigravity (AI-native development).
* **Language:** Python 3.10.
* **LLM Provider:** Google AI (Gemini 2.5 Pro for strategy, Gemini 2.5 Flash for data parsing).
* **Core APIs:**
    * **Yahoo Fantasy Sports API:** Primary source for current league state via `yahoofantasy` SDK.
    * **ESPN Fantasy API:** Secondary integration using `espn-api` Python library (Planned).
    * **nba_api:** Official NBA.com data for real-world player trends and advanced stats (Planned).
* **Storage:** Local JSON for authentication tokens; Pandas/CSV for historical stat tracking.
* **Frontend:** Streamlit for a fast "War Room" dashboard.

---

## 3. Architecture & Core Modules

### A. External Clients (`src/the_front_office/clients/`)
* **Goal:** Standardize interfaces for external services.
* **YahooFantasyClient:** Handles OAuth2 handshake and fetches rosters/stats.
* **NBAClient:** Fetches real-world stats and trends from NBA.com.
* **GeminiClient:** Encapsulates LLM logic for analysis.

### B. The AI Waiver Scanner (`src/the_front_office/scout.py`)
* **Goal:** Orchestrate clients to generate "Morning Scout Reports."
* **Logics:** Coordinates `YahooFantasyClient`, `NBAClient`, and `GeminiClient`.

### C. Trade War Room (`trade_analyzer.py`)
* **Goal:** Natural language trade evaluation (Planned).
* **Prompting:** Uses Gemini to analyze "Rest of Season" (ROS) value and category impact.

---

## 4. Phase 1 Implementation Plan

### Milestone 1: Connectivity
- [x] Create `.env` for Client ID and Client Secret.
- [x] Implement OAuth2 flow and session retrieval in `YahooProvider`.
- [x] Verify connection by printing current league standings and roster.

### Milestone 2: The Waiver Engine
- [x] Script to fetch the top 20 available Free Agents by 7-day performance.
- [x] Integrate Gemini 2.5 Pro to summarize the "Best Value" pickup for the current week, informed by **Matchup Context**.

### Milestone 3: Dashboard MVP
- [ ] Launch a Streamlit app that displays the AI-generated "Morning Scout Report."

---

## 5. Constraints & Security
* **Privacy:** Never commit `.env` or `.yahoofantasy` (token) files to version control.
* **Rate Limiting:** Implement 1-second delays between `nba_api` calls to avoid IP blocks.
* **Model Usage:** Use **Gemini 2.5 Pro** for strategic analysis and **Gemini 2.5 Flash** for high-volume data parsing.
* **League Focus:** Optimized specifically for **Category Leagues** (analyzing individual stat contributions like BLK, AST, FG%) rather than points or dynasty value.
* **Type Safety:** Maintain strict type checking with `mypy` and avoid `Any` types (Rules in `.agent/rules/rules.md`).
