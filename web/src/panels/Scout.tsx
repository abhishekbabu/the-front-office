import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type League, type Sport, type Summary } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { Loading } from "@/components/ui/state";
import { StatStrip } from "@/components/ui/stat";
import { LineupCard, SideCard } from "@/components/ui/lineup";
import { PlayerPanel } from "@/components/ui/player";
import { ErrorNote, PageHeader } from "@/panels/shared";

/**
 * The week: where you stand, what you are fielding, and who against.
 *
 * No analysis here. Everything is read or computed from league state, so the
 * page is complete the moment it opens — and the report, which lives on its own
 * view, is then an argument about what is already on screen rather than the
 * only thing on it.
 */
export function ScoutPanel({ sport, league }: { sport: Sport; league: League }) {
  const [open, setOpen] = useState<string | null>(null);

  const week = useQuery<Summary, Error>({
    queryKey: ["summary", sport.key, league.league_id],
    queryFn: () => api.summary(sport.key, league.league_id),
  });

  return (
    <>
      <PageHeader title={league.name} meta={league.detail} />
      <StatStrip stats={week.data?.headline ?? []} />

      {week.isLoading && <Loading lines={4} />}
      {week.isError && <ErrorNote error={week.error} />}

      {week.data && (
        <div className="flex flex-col gap-4 p-5">
          {week.data.opponent ? (
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
              <SideCard side={week.data.mine} label="You" onOpen={setOpen} />
              <SideCard side={week.data.opponent} label="Opponent" onOpen={setOpen} />
            </div>
          ) : (
            <LineupCard
              title="Your lineup"
              lineup={week.data.mine?.lineup ?? []}
              bench={week.data.mine?.bench ?? []}
              swaps={week.data.swaps}
              onOpen={setOpen}
            />
          )}

          {/* Shown beside the lineups when there is an opponent, since the
              swaps then have no card of their own to live in. */}
          {week.data.opponent && week.data.swaps.length > 0 && (
            <Card>
              <CardHeader>
                <span>Changes the projections imply</span>
              </CardHeader>
              {week.data.swaps.map((swap) => (
                <div
                  key={swap.start}
                  className="flex flex-wrap items-baseline gap-x-2 gap-y-1 border-t border-border px-4 py-2.5 text-[13px] first:border-t-0"
                >
                  <span className="font-medium">{swap.start}</span>
                  <span className="text-muted-foreground">for {swap.out || "an empty place"}</span>
                  <span className="ml-auto font-mono text-[12px] text-ok">{swap.gain}</span>
                </div>
              ))}
            </Card>
          )}

          {week.data.fixtures.length > 0 && (
            <Card>
              <CardHeader>
                <span>Watch out for</span>
              </CardHeader>
              <div className="flex flex-col">
                {week.data.fixtures.map((fixture) => (
                  <div
                    key={fixture.label}
                    className="flex items-baseline gap-3 border-t border-border px-4 py-2 text-[13px] first:border-t-0"
                  >
                    <span className="w-14 shrink-0 font-mono text-[11px] text-muted-foreground">{fixture.label}</span>
                    <span className={fixture.tone === "warning" ? "text-warn" : "text-muted-foreground"}>
                      {fixture.value}
                    </span>
                  </div>
                ))}
              </div>
            </Card>
          )}

          {!week.data.opponent && (
            <Badge variant="muted" appearance="label">
              No head-to-head fixture this week
            </Badge>
          )}
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
