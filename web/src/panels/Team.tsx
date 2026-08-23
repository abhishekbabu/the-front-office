import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type League, type PlayerCard, type Sport } from "@/lib/api";
import { Card, CardHeader } from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { Badge } from "@/components/ui/badge";
import { Empty, Loading } from "@/components/ui/state";
import { PlayerPanel } from "@/components/ui/player";
import { ErrorNote, PageHeader } from "@/panels/shared";

/** Columns whose values are figures, so they align right like numbers. */
const NUMERIC = new Set([
  "xPts", "Price", "Proj", "Points", "Form", "xGI", "Owned", "Depth", "Exp", "PTS", "REB", "AST",
]);

/**
 * Values that mean "look at this".
 *
 * The provider writes a status in the platform's own words — "doubtful 75%",
 * "Questionable", "OUT" — so anything non-empty is worth a badge, and the two
 * that mean definitely-not-playing get the stronger one.
 */
function statusTone(value: string): "fail" | "warn" {
  return /\b(out|suspended|injured|ir)\b/i.test(value) ? "fail" : "warn";
}

/**
 * The whole squad, in more depth than the week view.
 *
 * This is where you look at your players rather than at this week: the season
 * numbers, the ownership, the depth chart. Any row opens.
 */
export function TeamPanel({ sport, league }: { sport: Sport; league: League }) {
  const [open, setOpen] = useState<string | null>(null);

  const roster = useQuery<PlayerCard[], Error>({
    queryKey: ["roster", sport.key, league.league_id],
    queryFn: () => api.roster(sport.key, league.league_id),
  });

  return (
    <>
      <PageHeader title={league.name} meta={league.detail} />

      {roster.isError && <ErrorNote error={roster.error} />}
      {roster.isLoading && <Loading lines={5} />}

      {roster.data && (
        <div className="p-5">
          <Card>
            <CardHeader>
              <span>Squad</span>
              <span>{roster.data.length} players</span>
            </CardHeader>

            {roster.data.length === 0 ? (
              <Empty title="No players yet" detail="This roster is empty for the current season." />
            ) : (
              <DataTable
                rows={roster.data}
                numeric={NUMERIC}
                onSelect={(row) => setOpen(row.player_id)}
                render={(column, value) =>
                  column === "Status" && value ? (
                    <Badge variant={statusTone(value)} appearance="status">
                      {value}
                    </Badge>
                  ) : column === "Player" ? (
                    <span className="font-medium">{value}</span>
                  ) : column === "Slot" ? (
                    <span className="font-mono text-[11px] text-muted-foreground">{value}</span>
                  ) : undefined
                }
              />
            )}
          </Card>
        </div>
      )}

      <PlayerPanel
        sport={sport.key}
        league={league.league_id}
        playerId={open}
        onClose={() => setOpen(null)}
      />
    </>
  );
}
