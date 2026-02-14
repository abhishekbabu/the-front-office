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

### A. Auth Manager (`auth_manager.py`)
* **Goal:** Handle the OAuth2 handshake for Yahoo and ESPN.
* **Workflow:** Stores credentials securely in `.env` and tokens in `.yahoofantasy`.

### B. The AI Waiver Scanner (`scout.py`)
* **Goal:** Automatically scan available free agents.
* **Logic:** Compares roster against available free agents to suggest "Best Value" additions.
* **Context:** Ingests current roster (including players like **Kawhi Leonard**, **Naji Marshall**, **Jaylon Tyson**, and **Collin Murray-Boyles**) to avoid positional redundancy.

### C. Trade War Room (`trade_analyzer.py`)
* **Goal:** Natural language trade evaluation (Planned).
* **Prompting:** Uses Gemini to analyze "Rest of Season" (ROS) value and category impact.

---

## 4. Phase 1 Implementation Plan

### Milestone 1: Connectivity
- [x] Create `.env` for Client ID and Client Secret.
- [x] Implement `auth_manager.py` using the `yahoofantasy` library.
- [x] Verify connection by printing current league standings and roster.

### Milestone 2: The Waiver Engine
- [x] Script to fetch the top 20 available Free Agents by 7-day performance.
- [x] Integrate Gemini 2.5 Pro to summarize the "Best Value" pickup for the current week.

### Milestone 3: Dashboard MVP
- [ ] Launch a Streamlit app that displays the AI-generated "Morning Scout Report."

---

## 5. Constraints & Security
* **Privacy:** Never commit `.env` or `.yahoofantasy` (token) files to version control.
* **Rate Limiting:** Implement 1-second delays between `nba_api` calls to avoid IP blocks.
* **Model Usage:** Use **Gemini 2.5 Pro** for strategic analysis and **Gemini 2.5 Flash** for high-volume data parsing.
* **Type Safety:** Maintain strict type checking with `mypy` and avoid `Any` types.
