"""Projected nine-category totals for a matchup period.

Sleeper publishes NBA projections one row per player per game. A category
league scores on the totals across the games inside its matchup period, so the
rows for a player are filtered to that window and summed.

The join is by name, because Yahoo and Sleeper share no identifier. That is the
fragile part of this module and it is treated as such: names are normalized, an
ambiguous surname is refused rather than guessed, and a player who cannot be
matched simply carries no projection instead of borrowing someone else's.
"""

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from the_front_office.adapters.outbound.platforms.sleeper.types import GameProjection
from the_front_office.adapters.outbound.sports.names import NameIndex, normalize_name

logger = logging.getLogger(__name__)

# The nine scoring categories, plus the makes/attempts the percentages need.
COUNTING_STATS = ("pts", "reb", "ast", "stl", "blk", "to", "tpm")
SHOOTING_STATS = ("fgm", "fga", "ftm", "fta")


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
        grouped: dict[str, list[GameProjection]] = {}
        for row in rows:
            if _within(row.date, start, end):
                grouped.setdefault(normalize_name(row.name), []).append(row)

        self._index: NameIndex[list[GameProjection]] = NameIndex()
        for key, games in grouped.items():
            self._index.add(key, games)

    def __len__(self) -> int:
        return len(self._index)

    @property
    def is_empty(self) -> bool:
        """True out of season, when Sleeper publishes no projections yet."""
        return self._index.is_empty

    def lookup(self, name: str) -> ProjectedTotals | None:
        """Projected totals for `name`, or None if it cannot be matched."""
        rows = self._index.lookup(name)
        return aggregate(rows) if rows else None


def _within(value: str, start: date | None, end: date | None) -> bool:
    """Whether an ISO date falls inside the matchup period."""
    if start is None or end is None:
        return True
    try:
        day = date.fromisoformat(value)
    except ValueError:
        return False
    return start <= day <= end
