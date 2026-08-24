import { useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Search, X } from "lucide-react";
import { api, type League, type PlayerPage, type Competition } from "@/lib/api";
import { Card, CardHeader } from "@/components/ui/card";
import { IconButton } from "@/components/ui/icon-button";
import { RosterTable } from "@/components/ui/roster-table";
import type { SortState } from "@/components/ui/data-table";
import { Loading } from "@/components/ui/state";
import { PlayerPanel } from "@/components/ui/player";
import { ErrorNote, PageHeader } from "@/panels/shared";
import { cn } from "@/lib/utils";

const PAGE = 50;

/**
 * Who is still out there.
 *
 * The other half of a roster: what you hold is only half the question, and the
 * half that changes is the wire. Football's pool is four thousand players, so
 * this is a window onto a ranking rather than the ranking itself — which is
 * why the sort, the filters and the paging all happen on the server. Sorting
 * the fifty rows in hand would answer a different question than the one the
 * column header appears to ask.
 */
export function FreeAgentsPanel({ sport, league }: { sport: Competition; league: League }) {
  const [open, setOpen] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [position, setPosition] = useState("");
  const [sort, setSort] = useState<SortState | null>(null);
  const [offset, setOffset] = useState(0);

  const page = useQuery<PlayerPage, Error>({
    queryKey: ["free-agents", sport.key, league.league_id, search, position, sort, offset],
    queryFn: () =>
      api.freeAgents(sport.key, league.league_id, {
        offset,
        limit: PAGE,
        search,
        position,
        sort: sort?.column ?? "",
        descending: sort?.descending ?? true,
      }),
    // Keeps the table on screen while the next page loads, so paging does not
    // blink the page out and back.
    placeholderData: keepPreviousData,
  });

  /** Any change to what is being asked for starts again at the first page. */
  const reset = <T,>(set: (value: T) => void) => (value: T) => {
    set(value);
    setOffset(0);
  };

  const total = page.data?.total ?? 0;
  const shown = page.data?.players.length ?? 0;
  const filtered = Boolean(search || position);

  return (
    <>
      <PageHeader
        title={league.name}
        meta={league.detail}
        href={league.url}
        hrefLabel={`Open ${league.name} on the platform`}
      />

      {page.isError && <ErrorNote error={page.error} />}
      {page.isLoading && <Loading lines={6} />}

      {page.data && (
        <div className="flex flex-col gap-4 p-5">
          <Card>
            <CardHeader>
              <span>Available</span>
              <span>
                {total === 0
                  ? "none"
                  : `${offset + 1}-${offset + shown} of ${total.toLocaleString()}`}
              </span>
            </CardHeader>

            <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
              <div className="relative min-w-0 flex-1">
                <Search
                  className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground"
                  aria-hidden
                />
                <input
                  value={search}
                  onChange={(e) => reset(setSearch)(e.target.value)}
                  placeholder="Search by name, club or status"
                  aria-label="Search available players"
                  className="h-9 w-full rounded-md border border-border bg-background pl-8 pr-2 text-[13px] outline-none placeholder:text-muted-foreground focus-visible:border-ring"
                />
              </div>
              {/* Read off the pool rather than written down: the positions
                  differ per sport, and a list here would be a fourth place to
                  edit. Off the unfiltered pool, so choosing one does not
                  remove the others. */}
              {page.data.positions.map((p) => (
                <button
                  key={p}
                  onClick={() => reset(setPosition)(position === p ? "" : p)}
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
              {filtered && (
                <IconButton
                  label="Clear filters"
                  icon={<X />}
                  onClick={() => {
                    setSearch("");
                    setPosition("");
                    setOffset(0);
                  }}
                />
              )}
            </div>

            <RosterTable
              players={page.data.players}
              empty={{
                title: filtered ? "Nothing matches" : "Nobody available",
                detail: filtered
                  ? "Try a different position, or clear the search."
                  : "Every player in this league is on a roster.",
              }}
              sort={sort}
              onSort={reset(setSort)}
              onOpen={setOpen}
            />

            {total > PAGE && (
              <div className="flex items-center justify-between border-t border-border px-4 py-3">
                <span className="font-mono text-[11px] text-muted-foreground">
                  Page {Math.floor(offset / PAGE) + 1} of {Math.ceil(total / PAGE)}
                </span>
                <div className="flex items-center gap-1">
                  <IconButton
                    label="Previous page"
                    icon={<ChevronLeft />}
                    disabled={offset === 0}
                    onClick={() => setOffset(Math.max(0, offset - PAGE))}
                  />
                  <IconButton
                    label="Next page"
                    icon={<ChevronRight />}
                    disabled={offset + PAGE >= total}
                    onClick={() => setOffset(offset + PAGE)}
                  />
                </div>
              </div>
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
