"""Turning a ranked list of players into one window onto it.

Every sport builds its own ranking — a projection in football, expected points
in FPL, Yahoo's season rank in basketball — and then wants the same three
things done to it: keep the rows somebody asked for, order them by the column
they clicked, and hand back one page.

None of that is sport-specific, so none of it is written per sport. The one
thing a sport must supply is the number behind a formatted column, which it
does on the card: sorting "£15.5m" as text puts it below "£9.0m", and parsing
it back would mean teaching this module every sport's units.
"""

from thefrontoffice.domain.models import PlayerCard, PlayerPage, PlayerQuery

POSITION_COLUMN = "Pos"
"""Every sport names its position column this, which is what makes one
position filter work for all of them."""


def page(ranked: list[PlayerCard], query: PlayerQuery) -> PlayerPage:
    """Filter, order and window a list the sport has already ranked.

    The sport's own order is the default rather than a column sort, because
    that ranking is the answer to "who should I be looking at" and any column
    sort is a question about it.
    """
    positions = sorted({p.columns.get(POSITION_COLUMN, "") for p in ranked} - {""})

    matched = [card for card in ranked if _matches(card, query)]
    ordered = _ordered(matched, query)
    window = ordered[query.offset : query.offset + query.limit]
    return PlayerPage(players=window, total=len(matched), offset=query.offset, positions=positions)


def _matches(card: PlayerCard, query: PlayerQuery) -> bool:
    if query.position and card.columns.get(POSITION_COLUMN) != query.position:
        return False
    if not query.search:
        return True
    # Across every column rather than the name alone: a search is as often for
    # a club or a status as for a person.
    return query.search.casefold() in " ".join(card.columns.values()).casefold()


def _ordered(cards: list[PlayerCard], query: PlayerQuery) -> list[PlayerCard]:
    """Ordered by one column, with rows that have no value for it kept last.

    Last in both directions, which a sort key cannot express on its own: fold
    "is it missing" into the key and reversing the sort brings the blanks to
    the top, where they push every real answer off the first page.
    """
    if not query.sort:
        return cards

    numeric = any(query.sort in card.values for card in cards)
    has_value = (
        (lambda card: query.sort in card.values) if numeric else (lambda card: bool(card.columns.get(query.sort)))
    )
    key = (
        (lambda card: card.values[query.sort])
        if numeric
        else (lambda card: card.columns.get(query.sort, "").casefold())
    )

    present = [card for card in cards if has_value(card)]
    missing = [card for card in cards if not has_value(card)]
    return sorted(present, key=key, reverse=query.descending) + missing
