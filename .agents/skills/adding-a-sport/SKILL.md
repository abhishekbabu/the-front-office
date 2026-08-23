---
name: adding-a-sport
description: Add a new sport or fantasy platform to The Front Office. Use when wiring up a new league provider (FPL, ESPN, a second NBA platform), when a sport needs a capability the shared models lack, or when deciding where sport-specific logic belongs.
---

# Adding a Sport

This codebase exists to make this a small change. A sport is a provider plus a
prompt — no entry point, renderer or UI should learn its name.

## The five pieces

1. **Provider** — `adapters/outbound/sports/<sport>/<platform>.py`, implementing
   `SportProvider` from `domain/ports.py`. The filename is the platform that
   owns the **league**, not every platform the sport reads from: NBA leagues
   live on Yahoo, so the provider is `nba/yahoo.py` even though it also reads
   nba_stats and Sleeper. Naming it this way leaves room for the same sport on
   a second platform — `nba/sleeper.py` beside `nba/yahoo.py`.
   - `sport` / `label` class attributes
   - `list_leagues() -> list[LeagueRef]`
   - `build_context(league_id) -> SportContext`
   - `roster_rows(league_id) -> list[dict[str, str]]` — cheap; no projections or
     candidate pool
2. **Prompt template** in `config/constants.py`, rendered by `build_context`.
   Name it `<SPORT>_<REPORT>_PROMPT`.
3. **Canned mock report** in `domain/mocks.py`, registered in `MOCK_REPORTS`.
   A basketball mock returned for a football `--mock` run exercises the
   rendering path and tells you nothing about the prompt.
4. **Registration** — one `SportEntry` in `bootstrap.py`.
5. **Tests** — a fake platform client, and assertions on the *prompt content*:
   this is where the league rules actually live.

## Where other platforms go

A sport usually reads from more than one platform. Only the league platform
names a file; everything else is a role-named helper beside the provider:

```text
sports/nba/yahoo.py        provider — Yahoo owns the league
sports/nba/projections.py  projected totals, read from Sleeper
sports/nba/context.py      prompt lines, read from nba_stats
sports/nfl/sleeper.py      provider — Sleeper owns the league
sports/nfl/lineup.py       optimal lineup, computed from projections
```

Name helpers for what they produce, not where the data came from. A file called
`sleeper.py` under two different sports would mean two different things.

## Rules

**Never name a provider in an entry point.** The CLI, the web UI and the help
text all read `bootstrap.py`. If you are editing `adapters/inbound/` to add a
sport, the design has been bypassed.

**`is_configured` must be honest.** It gates whether a platform is contacted at
all. Building a provider may open an OAuth flow, and a user who does not play
that sport must never be made to sit through one. Check for the credentials the
provider actually needs, and nothing else.

**Widen the shared models; do not fork them.** `Move`, `ScoutReport` and
`TradeVerdict` are deliberately sport-neutral. If a sport needs a field they
lack, add it there and name it in the league's own vocabulary — `gains`, not
`categories_gained`. A second report type means a second renderer and a second
UI path.

**Compute what is computable.** Anything with an exact answer — an optimal
lineup, projected category totals, a transfer budget — belongs in code, handed
to the model as a fact to endorse or overrule. The model's job is judgement:
whether a projection is trustworthy, whether a matchup is bad, whether an injury
designation is real. See `adapters/outbound/sports/nfl/lineup.py`.

**Degrade, do not fail.** Enrichment that goes missing (trending players,
projections out of season, a matchup that has not started) should reduce the
prompt and say so, not raise. Reserve exceptions for things that make the answer
wrong: no team in the league, an unresolvable player in a trade.

## Joining players across platforms

Fantasy platforms and stats providers rarely share identifiers. When joining by
name (`adapters/outbound/sports/nba/projections.py` is the worked example):

- Normalise accents, punctuation and generational suffixes. A hyphen separates
  words (`Karl-Anthony` → `karl anthony`); an apostrophe does not (`De'Aaron` →
  `deaaron`).
- Refuse ambiguity. Two players sharing a surname must resolve to *neither*, not
  to whichever was indexed first.
- An unmatched player carries no data rather than borrowing someone else's.
- Measure the match rate against live data before trusting it.

## Reuse before you write

Check these before implementing anything a sport "needs":

| Need | Use |
|------|-----|
| Match a player name across platforms | `sports/names.py` — `NameIndex`, `normalise_name` |
| Resolve the players in a trade | `sports/trades.py` — `resolve_sides` |
| Retry a flaky platform call | `platforms/retry.py` — `build_retry`, `is_transient` |
| Cache a platform response | `platforms/cache.py` — `JsonDiskCache` |

If a second sport needs something the first already does, extract it into one of
those modules rather than copying it. Extract on the second instance, not the
third.

## Trades

Trade support is separate: implement `TradeProvider.build_trade_context` and set
`supports_trades=True` on the `SportEntry`. The engine, the prompt structure and
the verdict model are already shared.

## Checklist

- [ ] `just check` passes (lint, types, tests, 95% coverage floor)
- [ ] No adapter named in `domain/`, `application/` or `adapters/inbound/`
- [ ] Prompt assertions cover the league rules, not just that a string exists
- [ ] Out-of-season and unconfigured paths both tested
