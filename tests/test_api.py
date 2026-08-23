"""Tests for the web API.

The routes own transport and error rendering, so that is what is asserted here:
which status a failure becomes, what a client is told, and that a domain model
crosses the wire unchanged. The reports themselves are the engines' tests.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from the_front_office.adapters.inbound.web import api as web
from the_front_office.domain.mocks import MOCK_FPL_REPORT, MOCK_NBA_VERDICT
from the_front_office.domain.models import SportContext
from the_front_office.domain.ports import LeagueRef


class FakeProvider:
    """Stands in for any SportProvider."""

    sport = "fpl"
    label = "FPL (Fantasy Premier League)"

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def list_leagues(self) -> list[LeagueRef]:
        if self.error:
            raise self.error
        return [LeagueRef(league_id="900", name="Work League", sport="fpl", detail="3 of 12")]

    def roster_rows(self, league_id: str) -> list[dict[str, str]]:
        if self.error:
            raise self.error
        return [{"Player": "Haaland", "Pos": "FWD", "xPts": "7.4"}]

    def build_context(self, league_id: str) -> SportContext:
        return SportContext(prompt="prompt")

    def build_trade_context(self, league_id: str, proposal: Any) -> SportContext:
        return SportContext(prompt="prompt")


class FakeChat:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.sent: list[str] = []

    def send_message(self, message: str) -> Any:
        self.sent.append(message)
        if self.error:
            raise self.error
        from types import SimpleNamespace

        return SimpleNamespace(text="Because he has no fixture.")


@pytest.fixture(autouse=True)
def _clear_chats() -> None:
    web._chats.clear()
    _Engine.seen_mock.clear()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """A client whose providers and engines are fakes, so nothing leaves the process."""
    monkeypatch.setattr(web.data, "build_provider", lambda sport: FakeProvider())
    monkeypatch.setattr(web, "scout_engine", lambda p, mock: _Engine(mock))
    monkeypatch.setattr(web, "trade_engine", lambda p, mock: _Engine(mock))
    return TestClient(web.create_app())


class _Engine:
    """Records whether it was told to skip the model."""

    seen_mock: list[bool] = []

    def __init__(self, mock: bool) -> None:
        self.mock = mock
        _Engine.seen_mock.append(mock)

    def start_analysis(self, league_id: str) -> Any:
        return MOCK_FPL_REPORT, FakeChat()

    def evaluate(self, league_id: str, text: str) -> Any:
        return MOCK_NBA_VERDICT, FakeChat()


# ── the sport picker ────────────────────────────────────────────────────


def test_sports_include_the_unconfigured_ones(client: TestClient) -> None:
    """Hiding them would silently offer less than the app can do."""
    body = client.get("/api/sports").json()

    assert {s["sport"] for s in body} == {"nba", "nfl", "fpl"}
    assert all("requires" in s for s in body)


def test_a_sport_declares_whether_it_can_trade(client: TestClient) -> None:
    by_sport = {s["sport"]: s for s in client.get("/api/sports").json()}

    assert by_sport["nfl"]["supports_trades"] is True
    assert by_sport["fpl"]["supports_trades"] is False


# ── leagues and rosters ─────────────────────────────────────────────────


def test_leagues_are_listed(client: TestClient) -> None:
    body = client.get("/api/fpl/leagues").json()
    assert body == [{"league_id": "900", "name": "Work League", "detail": "3 of 12"}]


def test_a_roster_keeps_the_sports_own_columns(client: TestClient) -> None:
    """The client reads the keys off the data rather than being taught them."""
    body = client.get("/api/fpl/leagues/900/roster").json()
    assert list(body[0]) == ["Player", "Pos", "xPts"]


def test_an_unconfigured_sport_is_a_readable_400(monkeypatch: pytest.MonkeyPatch) -> None:
    """These are conditions the user can act on, not faults in the server."""
    client = TestClient(web.create_app())

    response = client.get("/api/nba/leagues")

    assert response.status_code == 400
    assert "not configured" in response.json()["detail"]


def test_a_platform_failure_reaches_the_client_in_words(monkeypatch: pytest.MonkeyPatch) -> None:
    from the_front_office.domain.errors import SleeperAPIError

    monkeypatch.setattr(web.data, "build_provider", lambda sport: FakeProvider(SleeperAPIError("Sleeper is down")))
    client = TestClient(web.create_app())

    response = client.get("/api/nfl/leagues")

    assert response.status_code == 400
    assert response.json()["detail"] == "Sleeper is down"


# ── reports ─────────────────────────────────────────────────────────────


def test_a_report_crosses_the_wire_as_the_domain_model(client: TestClient) -> None:
    """No second representation to keep in step with ScoutReport."""
    body = client.post("/api/fpl/leagues/900/scout").json()

    assert body["report"]["situation"] == MOCK_FPL_REPORT.situation
    assert body["report"]["moves"][0]["action"] == "CAPTAIN"
    assert body["chat_id"]


def test_whether_the_model_runs_is_read_from_configuration(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Read per request, so a change in Settings applies to the next run.

    A client cannot ask for a canned report: one place decides it, and that
    place is the same one the sidebar badge reads.
    """
    from the_front_office.config.settings import settings

    client.post("/api/fpl/leagues/900/scout")
    assert _Engine.seen_mock == [False]

    monkeypatch.setattr(settings, "mock_ai", True)
    client.post("/api/fpl/leagues/900/scout")
    assert _Engine.seen_mock == [False, True]


def test_a_verdict_crosses_the_wire_as_the_domain_model(client: TestClient) -> None:
    body = client.post("/api/nfl/leagues/900/trade", json={"text": "Give A, Get B"}).json()

    assert body["verdict"]["verdict"] == MOCK_NBA_VERDICT.verdict
    assert body["verdict"]["gains"] == MOCK_NBA_VERDICT.gains


def test_an_empty_trade_description_is_rejected_before_the_model(client: TestClient) -> None:
    assert client.post("/api/nfl/leagues/900/trade", json={"text": ""}).status_code == 422


def test_a_sport_without_trade_support_is_refused_by_name(client: TestClient) -> None:
    """FPL has no build_trade_context; without this the failure is an AttributeError."""
    response = client.post("/api/fpl/leagues/900/trade", json={"text": "Give A, Get B"})

    assert response.status_code == 400
    assert "does not support trade evaluation" in response.json()["detail"]


def test_an_unknown_sport_is_a_404(client: TestClient) -> None:
    response = client.post("/api/cricket/leagues/900/trade", json={"text": "Give A, Get B"})
    assert response.status_code == 404


# ── follow-up chat ──────────────────────────────────────────────────────


def test_a_follow_up_reaches_the_chat_the_report_opened(client: TestClient) -> None:
    chat_id = client.post("/api/fpl/leagues/900/scout").json()["chat_id"]

    body = client.post(f"/api/chat/{chat_id}", json={"message": "Why bench him?"}).json()

    assert body["answer"] == "Because he has no fixture."


def test_an_expired_conversation_says_so(client: TestClient) -> None:
    """Chats live in memory, so a restart loses them. Better said than answered blankly."""
    response = client.post("/api/chat/does-not-exist", json={"message": "Hi"})

    assert response.status_code == 404
    assert "expired" in response.json()["detail"]


def test_a_model_failure_is_a_bad_gateway_not_a_crash(client: TestClient) -> None:
    chat_id = client.post("/api/fpl/leagues/900/scout").json()["chat_id"]
    web._chats[chat_id] = FakeChat(RuntimeError("quota exhausted"))  # type: ignore[assignment]

    response = client.post(f"/api/chat/{chat_id}", json={"message": "Why?"})

    assert response.status_code == 502
    assert "quota exhausted" in response.json()["detail"]


def test_an_empty_follow_up_is_rejected(client: TestClient) -> None:
    chat_id = client.post("/api/fpl/leagues/900/scout").json()["chat_id"]
    assert client.post(f"/api/chat/{chat_id}", json={"message": ""}).status_code == 422


# ── serving the built UI ────────────────────────────────────────────────


def test_the_api_serves_without_a_built_front_end(client: TestClient) -> None:
    """`dist/` is absent during front-end development and in the test suite."""
    assert client.get("/api/sports").status_code == 200


# ── settings ────────────────────────────────────────────────────────────


@pytest.fixture
def settings_client(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """A client editing a throwaway .env rather than the developer's own."""
    from the_front_office.config import env_file

    path = tmp_path / ".env"
    path.write_text("SLEEPER_USERNAME=abhibeast\n", encoding="utf-8")
    monkeypatch.setattr(env_file, "ENV_PATH", path)
    monkeypatch.setattr(env_file, "reload_settings", lambda: None)
    return TestClient(web.create_app())


def test_settings_list_every_variable_the_app_reads(settings_client: TestClient) -> None:
    keys = {s["key"] for s in settings_client.get("/api/settings").json()}
    assert {"GOOGLE_API_KEY", "FPL_ENTRY_ID", "SLEEPER_USERNAME"} <= keys


def test_each_setting_declares_the_control_it_needs(settings_client: TestClient) -> None:
    """A page of text boxes invites a typo the validator then rejects on save."""
    kinds = {s["key"]: s["kind"] for s in settings_client.get("/api/settings").json()}

    assert kinds["MOCK_AI"] == "boolean"
    assert kinds["FPL_ENTRY_ID"] == "integer"
    assert kinds["NBA_API_DELAY"] == "number"
    assert kinds["LOG_LEVEL"] == "choice"
    assert kinds["SLEEPER_USERNAME"] == "text"


def test_a_fixed_set_of_values_is_offered_rather_than_typed(settings_client: TestClient) -> None:
    entry = next(s for s in settings_client.get("/api/settings").json() if s["key"] == "LOG_LEVEL")
    assert entry["choices"] == ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


def test_a_boolean_reports_its_effective_value_not_the_file_text(
    settings_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An absent key and a false one look identical in the file, so the UI would
    otherwise render an unset checkbox for a setting that is genuinely on."""
    from the_front_office.config.settings import settings

    monkeypatch.setattr(settings, "mock_ai", True)
    entry = next(s for s in settings_client.get("/api/settings").json() if s["key"] == "MOCK_AI")

    assert entry["value"] == "true"


def test_a_secret_is_never_sent_to_the_client(settings_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """There is nothing the UI can do with the characters of an API key that it
    cannot do with the fact that one is set — and a page that renders them puts
    them in screenshots."""
    from the_front_office.config.settings import settings

    monkeypatch.setattr(settings, "gemini_api_key", "super-secret-value")

    entry = next(s for s in settings_client.get("/api/settings").json() if s["key"] == "GOOGLE_API_KEY")

    assert entry["secret"] is True
    assert entry["present"] is True
    assert entry["value"] == ""


def test_a_non_secret_carries_its_value_so_it_can_be_edited(settings_client: TestClient) -> None:
    entry = next(s for s in settings_client.get("/api/settings").json() if s["key"] == "SLEEPER_USERNAME")
    assert entry["value"] == "abhibeast"


def test_saving_writes_the_value_and_returns_the_new_state(settings_client: TestClient) -> None:
    body = settings_client.put("/api/settings", json={"values": {"FPL_ENTRY_ID": "4242"}}).json()

    entry = next(s for s in body if s["key"] == "FPL_ENTRY_ID")
    assert entry["value"] == "4242"


def test_a_key_no_setting_reads_is_refused_with_its_name(settings_client: TestClient) -> None:
    response = settings_client.put("/api/settings", json={"values": {"GOOGLE_APIKEY": "oops"}})

    assert response.status_code == 400
    assert "GOOGLE_APIKEY" in response.json()["detail"]


def test_a_shell_variable_is_reported_so_a_futile_edit_is_visible(
    settings_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FPL_ENTRY_ID", "999")

    entry = next(s for s in settings_client.get("/api/settings").json() if s["key"] == "FPL_ENTRY_ID")

    assert entry["shadowed"] is True
