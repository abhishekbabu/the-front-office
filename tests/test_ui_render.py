"""Tests for the Streamlit rendering functions.

Streamlit's API is replaced with a recorder, so these run with no server and no
browser. They assert that every field of a report reaches the page — the failure
mode being a model field silently dropped from the UI.
"""

from types import SimpleNamespace
from typing import Any

import pytest

from the_front_office.domain.mocks import MOCK_SCOUT_REPORT, MOCK_TRADE_VERDICT
from the_front_office.domain.models import ScoutReport, TradeVerdict


class Recorder:
    """Captures every string Streamlit is asked to display."""

    def __init__(self) -> None:
        self.written: list[str] = []

    def _record(self, *args: Any, **kwargs: Any) -> "Recorder":
        for a in args:
            if isinstance(a, str):
                self.written.append(a)
        return self

    # Display calls
    write = subheader = markdown = success = info = caption = header = _record
    divider = _record

    def metric(self, label: str, value: Any) -> None:
        self.written.append(f"{label}:{value}")

    def columns(self, n: int) -> tuple["Recorder", ...]:
        return tuple(self for _ in range(n))

    def expander(self, label: str, expanded: bool = False) -> Any:
        self.written.append(label)
        return _NullContext()

    @property
    def text(self) -> str:
        return "\n".join(self.written)


class _NullContext:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *exc: Any) -> bool:
        return False


@pytest.fixture
def page(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    import the_front_office.adapters.inbound.web.app as app

    rec = Recorder()
    monkeypatch.setattr(app, "st", rec)
    return rec


def _app() -> Any:
    import the_front_office.adapters.inbound.web.app as app

    return app


# ── scout report ────────────────────────────────────────────────────────


def test_every_report_field_reaches_the_page(page: Recorder) -> None:
    _app().render_report(MOCK_SCOUT_REPORT)
    assert MOCK_SCOUT_REPORT.situation in page.text
    assert MOCK_SCOUT_REPORT.strategy in page.text
    for cat in MOCK_SCOUT_REPORT.focus:
        assert cat in page.text


def test_every_recommendation_is_rendered(page: Recorder) -> None:
    _app().render_report(MOCK_SCOUT_REPORT)
    for rec in MOCK_SCOUT_REPORT.moves:
        assert rec.player in page.text
        assert rec.rationale in page.text
        assert rec.replaces in page.text
        assert rec.replaces_rationale in page.text


def test_empty_target_list_says_so_rather_than_rendering_nothing(page: Recorder) -> None:
    report = ScoutReport(situation="x", focus=[], moves=[], strategy="y")
    _app().render_report(report)
    assert "no recommendations" in page.text


def test_monitor_entries_omit_the_drop_section(page: Recorder) -> None:
    rec = MOCK_SCOUT_REPORT.moves[0].model_copy(update={"action": "MONITOR", "replaces": "", "replaces_rationale": ""})
    _app().render_move(rec)
    assert "MONITOR" in page.text
    assert "Drop " not in page.text


def test_unknown_schedule_is_labelled_not_shown_as_zero(page: Recorder) -> None:
    rec = MOCK_SCOUT_REPORT.moves[0].model_copy(update={"metric": ""})
    _app().render_move(rec)
    assert "no metric" in page.text
    assert "0G left" not in page.text


# ── trade verdict ───────────────────────────────────────────────────────


def test_every_verdict_field_reaches_the_page(page: Recorder) -> None:
    _app().render_verdict(MOCK_TRADE_VERDICT)
    for field in ("verdict_detail", "impact", "schedule", "risk", "strategy"):
        assert getattr(MOCK_TRADE_VERDICT, field) in page.text


@pytest.mark.parametrize(("verdict", "colour"), [("ACCEPT", "green"), ("REJECT", "red"), ("COUNTER", "orange")])
def test_each_verdict_gets_its_own_colour(page: Recorder, verdict: str, colour: str) -> None:
    v = MOCK_TRADE_VERDICT.model_copy(update={"verdict": verdict})
    _app().render_verdict(v)
    assert f":{colour}[{verdict}]" in page.text


def test_empty_category_lists_render_a_dash(page: Recorder) -> None:
    v = TradeVerdict(
        verdict="REJECT",
        verdict_detail="d",
        gains=[],
        losses=[],
        impact="i",
        schedule="s",
        risk="r",
        strategy="st",
    )
    _app().render_verdict(v)
    assert "—" in page.text
    assert "Gains:0" in page.text


def test_verdict_colour_map_covers_every_allowed_verdict() -> None:
    """A new verdict literal without a colour would render gray silently."""
    import typing

    from the_front_office.domain.models import TradeVerdict as TV

    allowed = set(typing.get_args(TV.model_fields["verdict"].annotation))
    assert allowed == set(_app().VERDICT_COLOURS)


# ── follow-up chat ──────────────────────────────────────────────────────


def test_chat_is_skipped_when_no_session_exists(page: Recorder, monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app()
    monkeypatch.setattr(app.st, "session_state", {}, raising=False)
    app.render_chat("scout")
    assert page.text == ""


def test_chat_replays_history_and_appends_the_answer(page: Recorder, monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app()
    chat = SimpleNamespace(send_message=lambda q: SimpleNamespace(text="because of the schedule"))
    state: dict[str, Any] = {"scout_chat": chat, "scout_history": [("user", "why?")]}

    page.session_state = state  # type: ignore[attr-defined]
    page.chat_message = lambda role: _NullContext()  # type: ignore[attr-defined]
    page.spinner = lambda label: _NullContext()  # type: ignore[attr-defined]
    page.chat_input = lambda label, key=None: "and the drop?"  # type: ignore[attr-defined]

    app.render_chat("scout")

    assert "why?" in page.text  # prior turn replayed
    assert "because of the schedule" in page.text
    assert state["scout_history"][-1] == ("assistant", "because of the schedule")


def test_chat_errors_are_shown_not_raised(page: Recorder, monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app()

    def _boom(q: str) -> Any:
        raise RuntimeError("quota exceeded")

    state: dict[str, Any] = {"scout_chat": SimpleNamespace(send_message=_boom), "scout_history": []}
    page.session_state = state  # type: ignore[attr-defined]
    page.chat_message = lambda role: _NullContext()  # type: ignore[attr-defined]
    page.spinner = lambda label: _NullContext()  # type: ignore[attr-defined]
    page.chat_input = lambda label, key=None: "why?"  # type: ignore[attr-defined]

    app.render_chat("scout")
    assert "quota exceeded" in page.text


# ── page wiring ─────────────────────────────────────────────────────────


class Stopped(Exception):
    """Stands in for st.stop(), which halts the script."""


class FakeEntry:
    sport = "nfl"
    label = "NFL (Sleeper)"
    requires = "SLEEPER_USERNAME"
    supports_trades = False

    @staticmethod
    def is_configured() -> bool:
        return True


class FakeRef:
    def __init__(self, league_id: str = "L1", name: str = "My League", detail: str = "12-team") -> None:
        self.league_id, self.name, self.detail = league_id, name, detail


def _page_recorder(monkeypatch: pytest.MonkeyPatch, **extra: Any) -> Recorder:
    import the_front_office.adapters.inbound.web.app as app

    rec = Recorder()
    rec.error = rec.warning = rec._record  # type: ignore[attr-defined]
    rec.set_page_config = lambda **kw: None  # type: ignore[attr-defined]
    rec.sidebar = rec  # type: ignore[attr-defined]
    rec.title = rec._record  # type: ignore[attr-defined]
    rec.toggle = lambda label, help=None: False  # type: ignore[attr-defined]
    rec.radio = lambda label, options: options[0]  # type: ignore[attr-defined]
    rec.selectbox = lambda label, options: options[0]  # type: ignore[attr-defined]
    rec.button = lambda label, type=None, disabled=False: False  # type: ignore[attr-defined]
    rec.spinner = lambda label: _NullContext()  # type: ignore[attr-defined]
    rec.dataframe = lambda rows, **kw: rec.written.append(str(rows))  # type: ignore[attr-defined]
    rec.session_state = {}  # type: ignore[attr-defined]

    def _stop() -> None:
        raise Stopped

    rec.stop = _stop  # type: ignore[attr-defined]
    for k, v in extra.items():
        setattr(rec, k, v)
    monkeypatch.setattr(app, "st", rec)
    return rec


def test_no_configured_sports_explains_what_to_set(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app()
    rec = _page_recorder(monkeypatch)
    monkeypatch.setattr(app.data, "available_sports", lambda: [])
    with pytest.raises(Stopped):
        app.main()
    assert "SLEEPER_USERNAME" in rec.text


def test_choosing_a_sport_builds_only_that_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Building the NBA provider opens an OAuth flow; a football-only user must
    never trigger it."""
    app = _app()
    _page_recorder(monkeypatch)
    built: list[str] = []
    monkeypatch.setattr(app.data, "available_sports", lambda: [FakeEntry()])
    monkeypatch.setattr(app.data, "build_provider", lambda sport: built.append(sport) or object())
    monkeypatch.setattr(app, "scout_page", lambda entry, provider, mock: None)
    app.main()
    assert built == ["nfl"]


def test_an_unconfigured_provider_surfaces_its_message(monkeypatch: pytest.MonkeyPatch) -> None:
    from the_front_office.domain.errors import LeagueNotFoundError

    app = _app()
    rec = _page_recorder(monkeypatch)
    monkeypatch.setattr(app.data, "available_sports", lambda: [FakeEntry()])

    def _boom(sport: str) -> Any:
        raise LeagueNotFoundError("SLEEPER_USERNAME is not set in .env")

    monkeypatch.setattr(app.data, "build_provider", _boom)
    with pytest.raises(Stopped):
        app.main()
    assert "SLEEPER_USERNAME" in rec.text


def test_trade_is_offered_only_where_it_is_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    """A declared capability, not a hardcoded sport check."""
    app = _app()
    rec = _page_recorder(monkeypatch)
    seen: list[list[str]] = []
    rec.radio = lambda label, options: (seen.append(options), options[0])[1]  # type: ignore[attr-defined]
    monkeypatch.setattr(app.data, "available_sports", lambda: [FakeEntry()])
    monkeypatch.setattr(app.data, "build_provider", lambda sport: object())
    monkeypatch.setattr(app, "scout_page", lambda entry, provider, mock: None)
    app.main()
    views = next(o for o in seen if "Scout" in o)
    assert "Trade" not in views


def test_scout_page_renders_a_domain_error_instead_of_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    from the_front_office.domain.errors import TeamNotFoundError

    app = _app()
    rec = _page_recorder(monkeypatch)

    class Boom:
        def list_leagues(self) -> Any:
            raise TeamNotFoundError("Some League")

    app.scout_page(FakeEntry(), Boom(), mock=True)
    assert "Some League" in rec.text


def test_scout_page_warns_when_there_are_no_leagues(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app()
    rec = _page_recorder(monkeypatch)

    class NoLeagues:
        def list_leagues(self) -> Any:
            return []

    app.scout_page(FakeEntry(), NoLeagues(), mock=True)
    assert "No NFL (Sleeper) leagues" in rec.text


def test_team_page_renders_the_squad_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app()
    rec = _page_recorder(monkeypatch)

    class Provider:
        def list_leagues(self) -> Any:
            return [FakeRef()]

        def squad_rows(self, league_id: str) -> Any:
            return [{"Player": "Star QB", "Pos": "QB"}]

    app.team_page(FakeEntry(), Provider())
    assert "Star QB" in rec.text
    assert "My League" in rec.text


def test_a_single_league_is_not_offered_as_a_choice(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hierarchy in the model, collapsed in the UI."""
    app = _app()
    rec = _page_recorder(monkeypatch)
    asked: list[str] = []
    rec.selectbox = lambda label, options: asked.append(label) or options[0]  # type: ignore[attr-defined]
    assert app._pick_league([FakeRef()]).league_id == "L1"
    assert asked == []


def test_several_leagues_are_offered_as_a_choice(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _app()
    rec = _page_recorder(monkeypatch)
    rec.selectbox = lambda label, options: options[1]  # type: ignore[attr-defined]
    picked = app._pick_league([FakeRef("L1", "One"), FakeRef("L2", "Two")])
    assert picked.league_id == "L2"
