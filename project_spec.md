# Project "The Front Office": All-In-One NBA Fantasy Intelligence

## 1. Project Vision
An all-encompassing NBA Fantasy command center that transforms raw league data into competitive advantages. **The Front Office** serves as an AI-powered General Manager, capable of scouting the waiver wire, evaluating high-stakes trades, and providing natural language insights into team performance across multiple platforms (Yahoo/ESPN).

---

## 2. Technical Stack
* **IDE:** Antigravity (AI-native development).
* **Language:** Python 3.11+.
* **LLM Provider:** Google AI Pro (Gemini 1.5/2.0 Flash for data parsing; Gemini 3 Pro for complex strategy).
* **Core APIs:**
    * **Yahoo Fantasy Sports API:** Primary source for current league state via `yahoofantasy` SDK.
    * **ESPN Fantasy API:** Secondary integration using `espn-api` Python library.
    * **nba_api:** Official NBA.com data for real-world player trends and advanced stats.
* **Storage:** Local JSON for authentication tokens; Pandas/CSV for historical stat tracking.
* **Frontend:** Streamlit for a fast "War Room" dashboard.

---

## 3. Architecture & Core Modules

### A. Auth Manager (`auth_manager.py`)
* **Goal:** Handle the OAuth2 handshake for Yahoo and ESPN.
* **Workflow:** Stores credentials securely in `.env` and tokens in `oauth2.json`.

### B. The AI Waiver Scanner (`scout.py`)
* **Goal:** Automatically scan available free agents.
* **Logic:** Compares 7-day/14-day trends against the user’s roster weaknesses (e.g., identifies high-steal streamers for teams lacking in defensive categories).
* **Context:** Ingests current roster (including players like **Kawhi Leonard**, **Naji Marshall**, **Jaylon Tyson**, and **Collin Murray-Boyles**) to avoid positional redundancy.

### C. Trade War Room (`trade_analyzer.py`)
* **Goal:** Natural language trade evaluation.
* **Prompting:** Uses Gemini to analyze "Rest of Season" (ROS) value and category impact.

---

## 4. Phase 1 Implementation Plan

### Milestone 1: Connectivity
- [ ] Create `.env` for Client ID and Client Secret.
- [ ] Implement `auth_manager.py` using the `yahoofantasy` library.
- [ ] Verify connection by printing current league standings and roster.

### Milestone 2: The Waiver Engine
- [ ] Script to fetch the top 20 available Free Agents by 7-day performance.
- [ ] Integrate Gemini 1.5 Flash to summarize the "Best Value" pickup for the current week.

### Milestone 3: Dashboard MVP
- [ ] Launch a Streamlit app that displays the AI-generated "Morning Scout Report."

---

## 5. Constraints & Security
* **Privacy:** Never commit `.env` or `oauth2.json` to version control.
* **Rate Limiting:** Implement 1-second delays between `nba_api` calls to avoid IP blocks.
* **Model Usage:** Use **Gemini Flash** for recurring data tasks and **Pro** only for high-level trade analysis.
