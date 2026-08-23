"""Picking a starting eleven, and pricing a transfer.

Both have exact answers, so neither is asked of the model. Which legal eleven
maximises expected points is a small search over formations; what a transfer
costs is arithmetic on prices the game publishes. The model's job is the part
that is genuinely judgement — whether a projection is believable, whether a
run of fixtures is as kind as its difficulty ratings suggest, whether a knock
reported on Friday will clear by Saturday.

FPL constrains a lineup differently from a slot-based league: there are no named
slots, only a count of each position that must fall between a minimum and a
maximum. That is why this does not reuse the football lineup solver.
"""

from dataclasses import dataclass

from the_front_office.adapters.outbound.platforms.fpl.types import (
    FORMATION_LIMITS,
    STARTING_SIZE,
    Player,
)


def effective_points(player: Player) -> float:
    """Expected points, zeroed for a player the game says will not feature.

    The game leaves a stale `ep_next` on a ruled-out player, and starting one is
    a guaranteed blank rather than a small return.
    """
    if player.chance_of_playing == 0 or player.status in ("i", "s", "u", "n"):
        return 0.0
    return player.expected_points


def formations() -> list[dict[str, int]]:
    """Every legal distribution of eleven players across the four positions."""
    legal = []
    gk_min, gk_max = FORMATION_LIMITS["GKP"]
    for goalkeepers in range(gk_min, gk_max + 1):
        for defenders in range(*_span("DEF")):
            for midfielders in range(*_span("MID")):
                forwards = STARTING_SIZE - goalkeepers - defenders - midfielders
                low, high = FORMATION_LIMITS["FWD"]
                if low <= forwards <= high:
                    legal.append({"GKP": goalkeepers, "DEF": defenders, "MID": midfielders, "FWD": forwards})
    return legal


def _span(position: str) -> tuple[int, int]:
    low, high = FORMATION_LIMITS[position]
    return low, high + 1


@dataclass(frozen=True)
class Lineup:
    """A starting eleven, its captain, and the bench behind it."""

    starters: list[Player]
    bench: list[Player]
    captain: Player | None
    formation: str
    """The shape in the game's own notation, outfielders only: '3-5-2'."""

    @property
    def points(self) -> float:
        """Expected points with the captain counted twice."""
        total = sum(effective_points(p) for p in self.starters)
        return round(total + (effective_points(self.captain) if self.captain else 0.0), 2)


def best_lineup(squad: list[Player]) -> Lineup:
    """The highest-expecting legal eleven from a fifteen.

    Searched over every legal formation rather than filled greedily: taking the
    best eleven players outright routinely produces an illegal shape, and
    filling the tightest position first can strand points on the bench when a
    cheap defender would have freed a midfield slot.
    """
    by_position: dict[str, list[Player]] = {}
    for player in squad:
        by_position.setdefault(player.position, []).append(player)
    for players in by_position.values():
        players.sort(key=lambda p: (-effective_points(p), -p.form, p.name))

    best: list[Player] = []
    best_total = -1.0
    best_shape: dict[str, int] = {}
    for shape in formations():
        if any(len(by_position.get(pos, [])) < count for pos, count in shape.items()):
            continue
        eleven = [p for pos, count in shape.items() for p in by_position[pos][:count]]
        total = sum(effective_points(p) for p in eleven)
        if total > best_total:
            best, best_total, best_shape = eleven, total, shape

    starting_ids = {p.id for p in best}
    bench = sorted(
        (p for p in squad if p.id not in starting_ids),
        # Goalkeepers can only be substituted for goalkeepers, so the reserve
        # keeper sits apart from the ordered outfield bench.
        key=lambda p: (p.position != "GKP", -effective_points(p)),
    )
    captain = max(best, key=effective_points) if best else None
    shape = "-".join(str(best_shape.get(pos, 0)) for pos in ("DEF", "MID", "FWD")) if best_shape else ""
    return Lineup(starters=best, bench=bench, captain=captain, formation=shape)


@dataclass(frozen=True)
class LineupChange:
    """A player who should start, and the one they displace."""

    start: Player
    drop: Player | None

    @property
    def gain(self) -> float:
        return round(effective_points(self.start) - (effective_points(self.drop) if self.drop else 0.0), 2)


def lineup_changes(current_starters: list[Player], best: Lineup) -> list[LineupChange]:
    """What to change to reach `best`, largest gain first."""
    current_ids = {p.id for p in current_starters}
    best_ids = {p.id for p in best.starters}

    coming_in = sorted((p for p in best.starters if p.id not in current_ids), key=effective_points, reverse=True)
    going_out = sorted((p for p in current_starters if p.id not in best_ids), key=effective_points)

    changes = [
        LineupChange(start=player, drop=going_out[i] if i < len(going_out) else None)
        for i, player in enumerate(coming_in)
    ]
    return [c for c in changes if c.gain > 0]


MAX_OPTIONS_PER_PLAYER = 3
"""How many replacements to list for any one outgoing player."""


@dataclass(frozen=True)
class Transfer:
    """Swapping one squad player for one who is not in the squad."""

    out: Player
    incoming: Player

    @property
    def cost(self) -> int:
        """What the swap costs from the bank, in tenths of a million.

        Negative when the incoming player is cheaper, which frees money.
        Selling price can be below the current price when a player has risen
        since purchase, but the purchase price is only in `my-team`, so this is
        the optimistic bound and the prompt says so.
        """
        return self.incoming.cost - self.out.cost

    @property
    def gain(self) -> float:
        return round(effective_points(self.incoming) - effective_points(self.out), 2)


def affordable_transfers(
    squad: list[Player],
    market: list[Player],
    bank: int,
    limit: int = 12,
) -> list[Transfer]:
    """The best single-player upgrades this squad can pay for, best gain first.

    Only same-position swaps: FPL fixes how many of each position a squad holds,
    so a midfielder can only ever be replaced by a midfielder.
    """
    owned = {p.id for p in squad}
    candidates: dict[str, list[Player]] = {}
    for player in market:
        if player.id not in owned and player.is_available:
            candidates.setdefault(player.position, []).append(player)

    # One row per incoming player, paired with whoever they most improve on.
    # Ranking raw pairs instead fills the list with the same premium striker
    # opposite each of the squad's forwards — one suggestion wearing five hats.
    best_by_target: dict[int, Transfer] = {}
    for out in squad:
        for incoming in candidates.get(out.position, []):
            transfer = Transfer(out=out, incoming=incoming)
            if transfer.cost > bank or transfer.gain <= 0:
                continue
            existing = best_by_target.get(incoming.id)
            if existing is None or transfer.gain > existing.gain:
                best_by_target[incoming.id] = transfer
    # And at most a few alternatives for any one outgoing player, so the list
    # does not collapse onto the single weakest squad member.
    ranked = sorted(best_by_target.values(), key=lambda t: t.gain, reverse=True)
    seen: dict[int, int] = {}
    spread = []
    for transfer in ranked:
        count = seen.get(transfer.out.id, 0)
        if count >= MAX_OPTIONS_PER_PLAYER:
            continue
        seen[transfer.out.id] = count + 1
        spread.append(transfer)
    return spread[:limit]
