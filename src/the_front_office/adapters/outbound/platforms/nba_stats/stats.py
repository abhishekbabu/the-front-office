"""Nine-category arithmetic over cached game logs.

Pure functions over records — no network, no disk.
"""

import pandas as pd

from the_front_office.adapters.outbound.platforms.nba_stats.types import GameLogRecord, NineCatStats


def extract_nine_cat(records: list[GameLogRecord]) -> NineCatStats:
    """Average a run of games into a nine-category line.

    Percentages are computed from summed makes and attempts, not averaged from
    per-game percentages: the two differ whenever attempts vary between games,
    which is exactly when the number matters.
    """
    df = pd.DataFrame(records)
    mean_vals = df.mean(numeric_only=True)

    fga_sum, fgm_sum = df["FGA"].sum(), df["FGM"].sum()
    fta_sum, ftm_sum = df["FTA"].sum(), df["FTM"].sum()
    fg_pct = (fgm_sum / fga_sum) if fga_sum > 0 else 0.0
    ft_pct = (ftm_sum / fta_sum) if fta_sum > 0 else 0.0

    return NineCatStats(
        PTS=round(float(mean_vals.get("PTS", 0)), 1),
        REB=round(float(mean_vals.get("REB", 0)), 1),
        AST=round(float(mean_vals.get("AST", 0)), 1),
        STL=round(float(mean_vals.get("STL", 0)), 1),
        BLK=round(float(mean_vals.get("BLK", 0)), 1),
        TOV=round(float(mean_vals.get("TOV", 0)), 1),
        FG3M=round(float(mean_vals.get("FG3M", 0)), 1),
        FG_PCT=round(float(fg_pct), 3),
        FT_PCT=round(float(ft_pct), 3),
    )
