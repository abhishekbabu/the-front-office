"""Tests for the sport registry.

The registry is what makes adding a sport a one-file change: without it every
entry point named the providers itself, so a new sport meant editing the CLI,
the UI and the help text and remembering all three.
"""

import pytest

from the_front_office import bootstrap as registry
from the_front_office.config.settings import settings


def test_every_registered_sport_is_complete() -> None:
    for entry in registry.all_sports():
        assert entry.sport and entry.label and entry.requires
        assert callable(entry.build)
        assert callable(entry.is_configured)


def test_sport_keys_are_unique() -> None:
    keys = [e.sport for e in registry.all_sports()]
    assert len(keys) == len(set(keys))


def test_lookup_is_case_insensitive_and_tolerates_a_slash() -> None:
    assert registry.find("NFL") is registry.find("nfl")
    assert registry.find("/nfl") is registry.find("nfl")


def test_unknown_sport_is_none() -> None:
    assert registry.find("cricket") is None


def test_nothing_is_configured_without_credentials() -> None:
    """The autouse fixture blanks every credential, so this is the bare state."""
    assert registry.configured_sports() == []


def test_sleeper_needs_only_a_username(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sleeper is public — no key, no OAuth."""
    monkeypatch.setattr(settings, "sleeper_username", "someone")
    assert [e.sport for e in registry.configured_sports()] == ["nfl"]


def test_yahoo_needs_both_halves_of_the_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "yahoo_client_id", "id")
    assert registry.configured_sports() == []
    monkeypatch.setattr(settings, "yahoo_client_secret", "secret")
    assert [e.sport for e in registry.configured_sports()] == ["nba"]


def test_building_a_provider_is_deferred(monkeypatch: pytest.MonkeyPatch) -> None:
    """Constructing the registry must never contact a platform — the NBA build
    opens an OAuth flow, and a football-only user must not sit through it."""
    import the_front_office.adapters.outbound.platforms.yahoo.client as yahoo_mod

    def _must_not_run(*a: object, **k: object) -> None:
        raise AssertionError("Yahoo was contacted while listing sports")

    monkeypatch.setattr(yahoo_mod.YahooClient, "login", classmethod(_must_not_run))
    registry.all_sports()
    registry.configured_sports()
    registry.find("nba")


def test_the_nfl_entry_builds_a_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "sleeper_username", "someone")
    entry = registry.find("nfl")
    assert entry is not None
    assert entry.build().sport == "nfl"


def test_every_provider_satisfies_the_protocol() -> None:
    """A sport that forgets list_leagues, build_context or roster_rows would fail
    only at the point of use."""
    from the_front_office.adapters.outbound.sports.nba.yahoo import YahooNBAProvider
    from the_front_office.adapters.outbound.sports.nfl.sleeper import SleeperNFLProvider

    for provider in (YahooNBAProvider, SleeperNFLProvider):
        assert provider.sport and provider.label
        for method in ("list_leagues", "build_context", "roster_rows"):
            assert callable(getattr(provider, method, None)), f"{provider.__name__}.{method}"


def test_the_nba_entry_discovers_leagues_and_wraps_them(monkeypatch: pytest.MonkeyPatch) -> None:
    """The NBA build performs the Yahoo handshake, then hands the provider every
    league it found."""
    from types import SimpleNamespace

    import the_front_office.adapters.outbound.platforms.yahoo.client as yahoo_mod

    leagues = [SimpleNamespace(id="1", name="One", league_type="head"), SimpleNamespace(id="2", name="Two")]
    monkeypatch.setattr(yahoo_mod.YahooClient, "ensure_authorized", classmethod(lambda cls: None))
    monkeypatch.setattr(
        yahoo_mod.YahooClient,
        "get_context",
        classmethod(lambda cls: SimpleNamespace(get_leagues=lambda sport, season: leagues)),
    )

    entry = registry.find("nba")
    assert entry is not None
    provider = entry.build()
    assert [r.name for r in provider.list_leagues()] == ["One", "Two"]


def test_no_nba_leagues_is_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    import the_front_office.adapters.outbound.platforms.yahoo.client as yahoo_mod
    from the_front_office.domain.errors import LeagueNotFoundError

    monkeypatch.setattr(yahoo_mod.YahooClient, "ensure_authorized", classmethod(lambda cls: None))
    monkeypatch.setattr(
        yahoo_mod.YahooClient,
        "get_context",
        classmethod(lambda cls: SimpleNamespace(get_leagues=lambda sport, season: [])),
    )
    entry = registry.find("nba")
    assert entry is not None
    with pytest.raises(LeagueNotFoundError, match="no Yahoo NBA leagues"):
        entry.build()


def test_every_sport_declares_its_trade_support() -> None:
    """Declared on the entry so the CLI and UI need no per-sport branch."""
    for entry in registry.all_sports():
        assert isinstance(entry.supports_trades, bool)


def test_a_trading_sport_implements_the_trade_port() -> None:
    """`supports_trades` and `build_trade_context` must not drift apart."""
    from the_front_office.adapters.outbound.sports.fpl.fpl import FPLProvider
    from the_front_office.adapters.outbound.sports.nba.yahoo import YahooNBAProvider
    from the_front_office.adapters.outbound.sports.nfl.sleeper import SleeperNFLProvider

    implementations = {"nba": YahooNBAProvider, "nfl": SleeperNFLProvider, "fpl": FPLProvider}
    for entry in registry.all_sports():
        # A sport missing here is a sport the registry knows about and this
        # guard does not, which is the drift it exists to catch.
        provider = implementations[entry.sport]
        has_method = callable(getattr(provider, "build_trade_context", None))
        assert has_method == entry.supports_trades, entry.sport


def test_requirements_summary_names_every_sport() -> None:
    summary = registry.requirements_summary()
    for entry in registry.all_sports():
        assert entry.label in summary
        assert entry.requires in summary
