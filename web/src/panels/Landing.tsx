import { useQueries } from "@tanstack/react-query";
import { ChevronRight, Trophy } from "lucide-react";
import { api, type League, type Sport } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * What the app opens on: every league you are in, across every sport.
 *
 * The alternative — dropping straight into whichever sport happened to be
 * configured first — silently picks for you, and with three sports and several
 * leagues each it is picking wrong most of the time.
 */
export function Landing({
  sports,
  onPick,
}: {
  sports: Sport[];
  onPick: (sport: Sport, league: League) => void;
}) {
  const configured = sports.filter((s) => s.configured);

  // One query per sport rather than one combined endpoint: they fail
  // independently — an unauthorised Yahoo must not take the page down — and
  // each is cached under the same key the panels already use.
  const results = useQueries({
    queries: configured.map((sport) => ({
      queryKey: ["leagues", sport.sport],
      queryFn: () => api.leagues(sport.sport),
    })),
  });

  return (
    <div className="mx-auto max-w-3xl px-6 py-10">
      <div className="flex items-center gap-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground">
          <Trophy className="size-5" strokeWidth={2.25} aria-hidden />
        </span>
        <div>
          <h1 className="font-display text-2xl font-semibold tracking-tight">The Front Office</h1>
          <p className="font-mono text-[12px] text-muted-foreground">Pick a league to scout</p>
        </div>
      </div>

      <div className="mt-8 flex flex-col gap-4">
        {configured.map((sport, i) => {
          const result = results[i];
          return (
            <Card key={sport.sport}>
              <CardHeader>
                <span>{sport.label}</span>
                {result?.isSuccess && (
                  <span>
                    {result.data.length} {result.data.length === 1 ? "league" : "leagues"}
                  </span>
                )}
              </CardHeader>

              {result?.isLoading && <Skeleton className="m-4 h-14" />}

              {result?.isError && (
                // Shown in place rather than as a page-level failure: the other
                // sports are still usable, and this one names its own fix.
                <p className="px-4 py-3 text-[13px] leading-relaxed text-destructive">
                  {(result.error as Error).message}
                </p>
              )}

              {result?.isSuccess && result.data.length === 0 && (
                <p className="px-4 py-3 text-[13px] text-muted-foreground">
                  No leagues this season.
                </p>
              )}

              {result?.data?.map((league) => (
                <button
                  key={league.league_id}
                  onClick={() => onPick(sport, league)}
                  className="flex w-full items-center gap-3 border-t border-border px-4 py-3 text-left transition-colors hover:bg-muted"
                >
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-display text-[15px] font-semibold tracking-tight">
                      {league.name}
                    </div>
                    {league.detail && (
                      <div className="mt-0.5 truncate font-mono text-[11px] text-muted-foreground">
                        {league.detail}
                      </div>
                    )}
                  </div>
                  {!sport.supports_trades && (
                    <Badge variant="muted" appearance="label">
                      no trades
                    </Badge>
                  )}
                  <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                </button>
              ))}
            </Card>
          );
        })}
      </div>

      {sports.some((s) => !s.configured) && (
        <p className="mt-6 text-[13px] text-muted-foreground">
          {sports
            .filter((s) => !s.configured)
            .map((s) => s.label)
            .join(" and ")}{" "}
          {sports.filter((s) => !s.configured).length === 1 ? "is" : "are"} not configured — add
          credentials in Settings.
        </p>
      )}
    </div>
  );
}
