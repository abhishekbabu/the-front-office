import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search, X } from "lucide-react";
import { api, type League, type PlayerCard, type Sport } from "@/lib/api";
import { Card, CardHeader } from "@/components/ui/card";
import { IconButton } from "@/components/ui/icon-button";
import { RosterTable } from "@/components/ui/roster-table";
import { Loading } from "@/components/ui/state";
import { PlayerPanel } from "@/components/ui/player";
import { ErrorNote, PageHeader } from "@/panels/shared";
import { cn } from "@/lib/utils";

/**
 * Who is still out there.
 *
 * The other half of a roster: what you hold is only half the question, and the
 * half that changes is the wire. Ranked by the provider on whatever that sport
 * decides a signing on — a projection in football, the game's own expected
 * points in FPL — so the order is the answer and the filters only narrow it.
 */
export function FreeAgentsPanel({ sport, league }: { sport: Sport; league: League }) {
  const [open, setOpen] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [position, setPosition] = useState<string>("");

  const players = useQuery<PlayerCard[], Error>({
    queryKey: ["free-agents", sport.key, league.league_id],
    queryFn: () => api.freeAgents(sport.key, league.league_id),
  });

  // Read off the rows rather than hardcoded: the positions differ per sport,
  // and a list of them written here would be a fourth place to edit.
  const positions = useMemo(() => {
    const seen = new Set<string>();
    for (const player of players.data ?? []) {
      if (player.columns.Pos) seen.add(player.columns.Pos);
    }
    return [...seen].sort();
  }, [players.data]);

  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (players.data ?? []).filter(
      (p) =>
        (!position || p.columns.Pos === position) &&
        (!needle || Object.values(p.columns).join(" ").toLowerCase().includes(needle)),
    );
  }, [players.data, query, position]);

  return (
    <>
      <PageHeader
        title={league.name}
        meta={league.detail}
        href={league.url}
        hrefLabel={`Open ${league.name} on the platform`} />

      {players.isError && <ErrorNote error={players.error} />}
      {players.isLoading && <Loading lines={6} />}

      {players.data && (
        <div className="flex flex-col gap-4 p-5">
          <Card>
            <CardHeader>
              <span>Available</span>
              <span>
                {shown.length === players.data.length
                  ? `${shown.length} players`
                  : `${shown.length} of ${players.data.length}`}
              </span>
            </CardHeader>

            <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
              <div className="relative min-w-0 flex-1">
                <Search
                  className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground"
                  aria-hidden
                />
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search by name, club or status"
                  aria-label="Search available players"
                  className="h-9 w-full rounded-md border border-border bg-background pl-8 pr-2 text-[13px] outline-none placeholder:text-muted-foreground focus-visible:border-ring"
                />
              </div>
              {/* Positions are the filter that actually gets used — a wire is
                  browsed to fill a hole, and the hole has a position. */}
              {positions.map((p) => (
                <button
                  key={p}
                  onClick={() => setPosition(position === p ? "" : p)}
                  aria-pressed={position === p}
                  className={cn(
                    "h-9 rounded-md px-3 font-mono text-[11px] uppercase tracking-[0.06em] transition-colors",
                    position === p
                      ? "bg-primary text-primary-foreground"
                      : "border border-border text-muted-foreground hover:bg-muted",
                  )}
                >
                  {p}
                </button>
              ))}
              {(query || position) && (
                <IconButton
                  label="Clear filters"
                  icon={<X />}
                  onClick={() => {
                    setQuery("");
                    setPosition("");
                  }}
                />
              )}
            </div>

            <RosterTable
              players={shown}
              empty={{
                title: query || position ? "Nothing matches" : "Nobody available",
                detail:
                  query || position
                    ? "Try a different position, or clear the search."
                    : "Every player in this league is on a roster.",
              }}
              onOpen={setOpen}
            />
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
