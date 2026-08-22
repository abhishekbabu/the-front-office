"""Streamlit front end.

Lays out the same validated models the CLI renders. Nothing here computes
anything — the engines produce the reports.

Run with `just ui`.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from the_front_office.adapters.inbound.web import data
from the_front_office.bootstrap import requirements_summary, scout_engine, trade_engine
from the_front_office.config.logging import setup_logging
from the_front_office.domain.errors import FrontOfficeError
from the_front_office.domain.models import Move, ScoutReport, TradeVerdict

VERDICT_COLOURS = {"ACCEPT": "green", "REJECT": "red", "COUNTER": "orange"}


# ── cached resources ────────────────────────────────────────────────────
# Streamlit reruns this script on every interaction; without caching, each
# click would re-authenticate and re-read the NBA cache from disk.

_nba_client = st.cache_resource(show_spinner=False)(data.nba_client)


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
    gained.metric("Gains", len(verdict.gains))
    gained.write(" ".join(f"`{c}`" for c in verdict.gains) or "—")
    lost.metric("Losses", len(verdict.losses))
    lost.write(" ".join(f"`{c}`" for c in verdict.losses) or "—")

    for heading, body in [
        ("Impact", verdict.impact),
        ("Schedule", verdict.schedule),
        ("Risk", verdict.risk),
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


def scout_page(entry: Any, provider: Any, mock: bool) -> None:
    """Scouting report for whichever sport is selected."""
    st.header(f"{entry.label} report")

    try:
        refs = provider.list_leagues()
    except FrontOfficeError as e:
        st.error(str(e))
        return
    if not refs:
        st.warning(f"No {entry.label} leagues found for this season.")
        return

    ref = _pick_league(refs)
    key = f"scout_{entry.sport}"

    if st.button("Run report", type="primary"):
        with st.spinner("Gathering league state and building the report…"):
            try:
                report, chat = scout_engine(provider, mock).start_analysis(ref.league_id)
            except FrontOfficeError as e:
                st.error(str(e))
                return
        st.session_state[f"{key}_report"] = report
        st.session_state[f"{key}_chat"] = chat
        st.session_state[f"{key}_history"] = []

    report = st.session_state.get(f"{key}_report")
    if report is not None:
        render_report(report)
        render_chat(key)


def team_page(entry: Any, provider: Any) -> None:
    """Roster view for whichever sport is selected."""
    try:
        refs = provider.list_leagues()
    except FrontOfficeError as e:
        st.error(str(e))
        return
    if not refs:
        st.warning(f"No {entry.label} leagues found for this season.")
        return

    ref = _pick_league(refs)
    st.header(ref.name)
    if ref.detail:
        st.caption(ref.detail)

    try:
        rows = provider.squad_rows(ref.league_id)
    except FrontOfficeError as e:
        st.error(str(e))
        return
    st.subheader("Roster")
    st.dataframe(rows, hide_index=True, use_container_width=True)


def trade_page(entry: Any, provider: Any, mock: bool) -> None:
    """Trade evaluation, for whichever sport declares support."""
    st.header("Trade evaluation")
    st.caption("Describe a trade in plain language.")

    try:
        refs = provider.list_leagues()
    except FrontOfficeError as e:
        st.error(str(e))
        return
    if not refs:
        st.warning(f"No {entry.label} leagues found for this season.")
        return
    ref = _pick_league(refs)

    text = st.text_input("Trade", placeholder="Give LeBron James, Get Jayson Tatum")
    if st.button("Evaluate", type="primary", disabled=not text):
        with st.spinner("Parsing, enriching and evaluating…"):
            try:
                verdict, chat = trade_engine(provider, mock).evaluate(ref.league_id, text)
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


def _pick_league(refs: list[Any]) -> Any:
    """League selector, collapsed to a caption when there is only one."""
    if len(refs) == 1:
        return refs[0]
    labels = [f"{r.name} — {r.detail}" if r.detail else r.name for r in refs]
    return refs[labels.index(st.selectbox("League", labels))]


# ── entry point ─────────────────────────────────────────────────────────


def main() -> None:
    st.set_page_config(page_title="The Front Office", page_icon="🏆", layout="wide")
    setup_logging()

    st.sidebar.title("🏆 The Front Office")
    mock = st.sidebar.toggle("Mock AI", help="Skip Gemini calls. League data stays live.")

    entries = data.available_sports()
    if not entries:
        st.error("No sports configured. In .env set — " + requirements_summary())
        st.stop()

    labels = [e.label for e in entries]
    chosen = st.sidebar.radio("Sport", labels) if len(labels) > 1 else labels[0]
    entry = entries[labels.index(chosen)]

    views = ["Scout", "My team"] + (["Trade"] if entry.supports_trades else [])
    page = st.sidebar.radio("View", views)

    try:
        provider = data.build_provider(entry.sport)
    except FrontOfficeError as e:
        st.error(str(e))
        st.stop()

    if page == "Scout":
        scout_page(entry, provider, mock)
    elif page == "My team":
        team_page(entry, provider)
    else:
        trade_page(entry, provider, mock)


# Streamlit executes this script with __name__ == "__main__", so the guard runs
# the app under `streamlit run` while leaving the module importable for tests.
if __name__ == "__main__":
    main()
