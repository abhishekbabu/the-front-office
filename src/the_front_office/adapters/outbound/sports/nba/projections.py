"""Projected nine-category totals for a matchup period.

Sleeper publishes NBA projections one row per player per game. A category
league scores on the totals across the games inside its matchup period, so the
rows for a player are filtered to that window and summed.

The join is by name, because Yahoo and Sleeper share no identifier. That is the
fragile part of this module and it is treated as such: names are normalised, an
ambiguous surname is refused rather than guessed, and a player who cannot be
matched simply carries no projection instead of borrowing someone else's.
"""

import logging
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from the_front_office.adapters.outbound.platforms.sleeper.types import GameProjection

logger = logging.getLogger(__name__)

# The nine scoring categories, plus the makes/attempts the percentages need.
COUNTING_STATS = ("pts", "reb", "ast", "stl", "blk", "to", "tpm")
SHOOTING_STATS = ("fgm", "fga", "ftm", "fta")

_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def normalise_name(name: str) -> str:
    """Reduce a name to a comparable key.

    Strips accents, punctuation and generational suffixes, so "Luka Dončić",
    "Luka Doncic" and "Jaren Jackson Jr." all match across platforms.
    """
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    # A hyphen separates words, an apostrophe does not: "Karl-Anthony" becomes
    # "karl anthony", "De'Aaron" becomes "deaaron".
    spaced = ascii_only.lower().replace("-", " ").replace(".", " ")
    cleaned = re.sub(r"[^a-z ]", "", spaced)
    parts = [p for p in cleaned.split() if p and p not in _SUFFIXES]
    return " ".join(parts)


@dataclass(frozen=True)
class ProjectedTotals:
    """A player's projected category totals across a matchup period."""

    games: int
    totals: dict[str, float]

    @property
    def fg_pct(self) -> float | None:
        return _ratio(self.totals.get("fgm"), self.totals.get("fga"))

    @property
    def ft_pct(self) -> float | None:
        return _ratio(self.totals.get("ftm"), self.totals.get("fta"))

    def summary(self) -> str:
        """A one-line nine-category summary, in the prompt's usual shape."""
        t = self.totals
        parts = [
            f"{self.games}G",
            f"{t.get('pts', 0):.0f}p",
            f"{t.get('reb', 0):.0f}r",
            f"{t.get('ast', 0):.0f}a",
            f"{t.get('stl', 0):.1f}s",
            f"{t.get('blk', 0):.1f}b",
            f"{t.get('to', 0):.1f}to",
            f"{t.get('tpm', 0):.0f}tpm",  # not "3pm": "5" + "3pm" reads as "53pm"
        ]
        if (fg := self.fg_pct) is not None:
            parts.append(f"FG{fg:.1%}")
        if (ft := self.ft_pct) is not None:
            parts.append(f"FT{ft:.1%}")
        return " ".join(parts)


def _ratio(made: float | None, attempted: float | None) -> float | None:
    """Percentage from totals, not an average of per-game percentages."""
    if not attempted:
        return None
    return (made or 0.0) / attempted


def aggregate(rows: Iterable[GameProjection]) -> ProjectedTotals:
    """Sum per-game projections into category totals."""
    rows = list(rows)
    totals: dict[str, float] = {}
    for stat in (*COUNTING_STATS, *SHOOTING_STATS):
        value = sum(r.stats.get(stat, 0.0) for r in rows)
        if value:
            totals[stat] = round(value, 2)
    return ProjectedTotals(games=len(rows), totals=totals)


class ProjectionIndex:
    """Projections for a matchup period, looked up by player name."""

    def __init__(self, rows: Iterable[GameProjection], start: date | None, end: date | None) -> None:
        self._by_name: dict[str, list[GameProjection]] = {}
        self._ambiguous_surnames: set[str] = set()
        by_surname: dict[str, set[str]] = {}

        for row in rows:
            if not _within(row.date, start, end):
                continue
            key = normalise_name(row.name)
            if not key:
                continue
            self._by_name.setdefault(key, []).append(row)
            surname = key.rsplit(" ", 1)[-1]
            by_surname.setdefault(surname, set()).add(key)

        self._by_surname = {s: next(iter(k)) for s, k in by_surname.items() if len(k) == 1}
        self._ambiguous_surnames = {s for s, k in by_surname.items() if len(k) > 1}

    def __len__(self) -> int:
        return len(self._by_name)

    @property
    def is_empty(self) -> bool:
        """True out of season, when Sleeper publishes no projections yet."""
        return not self._by_name

    def lookup(self, name: str) -> ProjectedTotals | None:
        """Projected totals for `name`, or None if it cannot be matched.

        Falls back to a surname match only when that surname is unique in the
        index — two Jacksons must not resolve to whichever came first.
        """
        key = normalise_name(name)
        rows = self._by_name.get(key)

        if rows is None:
            surname = key.rsplit(" ", 1)[-1] if key else ""
            if surname in self._ambiguous_surnames:
                logger.debug(f"Ambiguous surname for {name!r}; no projection applied")
                return None
            matched = self._by_surname.get(surname)
            rows = self._by_name.get(matched) if matched else None

        if not rows:
            return None
        return aggregate(rows)


def _within(value: str, start: date | None, end: date | None) -> bool:
    """Whether an ISO date falls inside the matchup period."""
    if start is None or end is None:
        return True
    try:
        day = date.fromisoformat(value)
    except ValueError:
        return False
    return start <= day <= end
