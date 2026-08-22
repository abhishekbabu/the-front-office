"""Streamlit front end.

Renders the same validated models the CLI does — see the_front_office.render for
the terminal equivalent. Nothing here computes anything: the engines produce
ScoutReport and TradeVerdict, and this module lays them out.

Run with `just ui`.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from the_front_office.config.logging import setup_logging
from the_front_office.exceptions import FrontOfficeError
from the_front_office.report.engine import ScoutEngine
from the_front_office.report.types import Move, ScoutReport
from the_front_office.sports.nba.provider import NBAProvider
from the_front_office.sports.nfl.provider import NFLProvider
from the_front_office.trade.engine import TradeEvaluator
from the_front_office.trade.types import TradeVerdict
from the_front_office.ui import data

VERDICT_COLOURS = {"ACCEPT": "green", "REJECT": "red", "COUNTER": "orange"}


# ── cached resources ────────────────────────────────────────────────────
# Streamlit reruns this script on every interaction; without caching, each
# click would re-authenticate and re-read the NBA cache from disk.

_load_leagues = st.cache_resource(show_spinner=False)(data.load_leagues)
_nba_client = st.cache_resource(show_spinner=False)(data.nba_client)


@st.cache_data(show_spinner=False)
def _roster_rows(_team: Any, team_name: str) -> list[dict[str, str]]:
    """Cached per team name — the Yahoo object itself is not hashable."""
    return data.roster_rows(_team)


# ── rendering ───────────────────────────────────────────────────────────


def render_move(rec: Move) -> None:
    """One waiver move as an expandable card."""
    header = f"{rec.action}  ·  {rec.player}  ({rec.position}, {rec.team})  ·  {rec.metric or 'no metric'}"

    with st.expander(header, expanded=True):
        if []:
            st.write(" ".join(f"`{c}`" for c in []))
        st.write(rec.rationale)
        if rec.replaces:
            st.divider()
            st.markdown(f"**{rec.replaces}** — {rec.replaces_rationale}")


def render_report(report: ScoutReport) -> None:
    """A full scout report."""
    st.subheader("Situation")
    st.write(report.situation)
    if report.focus:
        st.write("**In play:** " + " ".join(f"`{c}`" for c in report.focus))

    st.subheader("Moves")
    if not report.moves:
        st.info("The model returned no recommendations.")
    for rec in report.moves:
        render_move(rec)

    st.subheader("Strategy")
    st.success(report.strategy)


def render_verdict(verdict: TradeVerdict) -> None:
    """A full trade verdict."""
    colour = VERDICT_COLOURS.get(verdict.verdict, "gray")
    st.markdown(f"## :{colour}[{verdict.verdict}]")
    st.write(verdict.verdict_detail)

    gained, lost = st.columns(2)
    gained.metric("Categories gained", len(verdict.categories_gained))
    gained.write(" ".join(f"`{c}`" for c in verdict.categories_gained) or "—")
    lost.metric("Categories lost", len(verdict.categories_lost))
    lost.write(" ".join(f"`{c}`" for c in verdict.categories_lost) or "—")

    for heading, body in [
        ("Impact", verdict.impact),
        ("Schedule", verdict.schedule_note),
        ("Shutdown risk", verdict.shutdown_risk),
        ("Strategy", verdict.strategy),
    ]:
        st.subheader(heading)
        st.write(body)


def render_chat(key: str) -> None:
    """Follow-up conversation against the chat session in st.session_state."""
    chat = st.session_state.get(f"{key}_chat")
    if chat is None:
        return

    history_key = f"{key}_history"
    history: list[tuple[str, str]] = st.session_state.setdefault(history_key, [])

    st.divider()
    st.subheader("Ask a follow-up")
    for role, text in history:
        with st.chat_message(role):
            st.write(text)

    question = st.chat_input("e.g. why that drop?", key=f"{key}_input")
    if not question:
        return

    history.append(("user", question))
    with st.chat_message("user"):
        st.write(question)
    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            try:
                answer = chat.send_message(question).text or "(no answer)"
            except Exception as e:  # the SDK raises its own error types
                answer = f"Error: {e}"
        st.write(answer)
    history.append(("assistant", answer))


# ── pages ───────────────────────────────────────────────────────────────


def football_page(mock: bool) -> None:
    """Weekly Sleeper report: start/sit and waiver targets."""
    st.header("Football report")
    st.caption("Start/sit and waiver targets for the current NFL week.")

    provider = NFLProvider()
    try:
        refs = provider.list_leagues()
    except FrontOfficeError as e:
        st.error(str(e))
        return

    if not refs:
        st.warning("No Sleeper NFL leagues found for this season.")
        return

    names = [f"{r.name} — {r.detail}" for r in refs]
    chosen = st.selectbox("League", names) if len(names) > 1 else names[0]
    ref = refs[names.index(chosen)]

    if st.button("Run football report", type="primary"):
        with st.spinner("Pulling rosters, projections and waiver pool…"):
            try:
                report, chat = ScoutEngine(provider, mock_ai=mock).start_analysis(ref.league_id)
            except FrontOfficeError as e:
                st.error(str(e))
                return
        st.session_state["football_report"] = report
        st.session_state["football_chat"] = chat
        st.session_state["football_history"] = []

    report = st.session_state.get("football_report")
    if report is not None:
        render_report(report)
        render_chat("football")


def scout_page(league: Any, mock: bool) -> None:
    st.header("Scout report")
    st.caption("Waiver wire analysis for the current matchup.")

    if st.button("Run scout report", type="primary"):
        with st.spinner("Analysing roster, free agents and schedule…"):
            try:
                report, chat = ScoutEngine(NBAProvider(league, nba=_nba_client()), mock_ai=mock).start_analysis("")
            except FrontOfficeError as e:
                st.error(str(e))
                return
        st.session_state["scout_report"] = report
        st.session_state["scout_chat"] = chat
        st.session_state["scout_history"] = []

    report = st.session_state.get("scout_report")
    if report is not None:
        render_report(report)
        render_chat("scout")


def trade_page(league: Any, mock: bool) -> None:
    st.header("Trade evaluation")
    st.caption("Describe a trade in plain language.")

    text = st.text_input("Trade", placeholder="Give LeBron James, Get Jayson Tatum")
    if st.button("Evaluate", type="primary", disabled=not text):
        with st.spinner("Parsing, enriching and evaluating…"):
            try:
                verdict, chat = TradeEvaluator(league, mock_ai=mock, nba=_nba_client()).evaluate(text)
            except FrontOfficeError as e:
                st.error(str(e))
                return
        st.session_state["trade_verdict"] = verdict
        st.session_state["trade_chat"] = chat
        st.session_state["trade_history"] = []

    verdict = st.session_state.get("trade_verdict")
    if verdict is not None:
        render_verdict(verdict)
        render_chat("trade")


def team_page(league: Any) -> None:
    from the_front_office.clients.yahoo.client import YahooFantasyClient

    yahoo = YahooFantasyClient(league)
    try:
        team = yahoo.get_user_team()
    except FrontOfficeError as e:
        st.error(str(e))
        return

    st.header(team.name)

    st.subheader("Matchup")
    rows = data.matchup_rows(yahoo.get_matchup_context(team))
    if rows:
        st.dataframe(rows, hide_index=True, use_container_width=True)
    else:
        st.info("No matchup in progress.")

    st.subheader("Roster")
    st.dataframe(_roster_rows(team, team.name), hide_index=True, use_container_width=True)


# ── entry point ─────────────────────────────────────────────────────────


def main() -> None:
    st.set_page_config(page_title="The Front Office", page_icon="🏀", layout="wide")
    setup_logging()

    st.sidebar.title("🏀 The Front Office")
    mock = st.sidebar.toggle("Mock AI", help="Skip Gemini calls. Yahoo data stays live.")

    sport = st.sidebar.radio("Sport", ["NBA (Yahoo)", "NFL (Sleeper)"])

    if sport == "NFL (Sleeper)":
        # Sleeper needs no auth, so the football path skips the Yahoo handshake
        # entirely rather than blocking on credentials it does not use.
        football_page(mock)
        return

    try:
        leagues = _load_leagues()
    except Exception as e:
        st.error(f"Could not reach Yahoo: {e}")
        st.stop()

    if not leagues:
        st.warning("No NBA leagues found for this season.")
        st.stop()

    names = [lg.name for lg in leagues]
    chosen = st.sidebar.selectbox("League", names) if len(names) > 1 else names[0]
    league = leagues[names.index(chosen)]

    page = st.sidebar.radio("View", ["Scout", "Trade", "My team"])
    if page == "Scout":
        scout_page(league, mock)
    elif page == "Trade":
        trade_page(league, mock)
    else:
        team_page(league)


# Streamlit executes this script with __name__ == "__main__", so the guard runs
# the app under `streamlit run` while leaving the module importable for tests.
if __name__ == "__main__":
    main()
