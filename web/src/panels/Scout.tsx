import { useMutation, useQuery } from "@tanstack/react-query";
import { api, type Analysis, type League, type Sport, type Summary } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { StatStrip } from "@/components/ui/stat";
import { LineupCard } from "@/components/ui/lineup";
import { Chat, Chips, ErrorNote, MoveRow, PageHeader } from "@/panels/shared";

export function ScoutPanel({ sport, league, ai }: { sport: Sport; league: League; ai: boolean }) {
  // Loaded on arrival rather than with the report: every figure in it is
  // already known, and a page that shows nothing until a model has answered is
  // blank for as long as that takes.
  const standing = useQuery<Summary, Error>({
    queryKey: ["summary", sport.sport, league.league_id],
    queryFn: () => api.summary(sport.sport, league.league_id),
  });

  const run = useMutation<Analysis, Error>({
    mutationFn: () => api.scout(sport.sport, league.league_id),
  });

  // The report carries its own, computed the same way; before one exists the
  // standing stands in.
  const headline = run.data?.report.headline ?? standing.data?.headline ?? [];

  return (
    <>
      <PageHeader title={league.name} meta={league.detail}>
        {ai && (
          <Button variant="primary" onClick={() => run.mutate()} disabled={run.isPending}>
            {run.isPending ? "Building…" : run.data ? "Run again" : "Run report"}
          </Button>
        )}
      </PageHeader>

      <StatStrip stats={headline} />
      {standing.isLoading && <Skeleton className="mx-5 mt-4 h-12" />}
      {standing.isError && !run.data && <ErrorNote error={standing.error} />}

      {run.isError && <ErrorNote error={run.error} />}

      {run.isPending && (
        <div className="flex flex-col gap-3 p-5">
          <Skeleton className="h-4 w-64" />
          <Skeleton className="h-28 w-full" />
          <Skeleton className="h-28 w-full" />
        </div>
      )}

      {run.data && (
        <div className="flex flex-col gap-4 p-5">
          <Card>
            <CardHeader>
              <span>Situation</span>
              <span>
                {run.data.report.moves.length} {run.data.report.moves.length === 1 ? "move" : "moves"}
              </span>
            </CardHeader>
            <div className="p-4 pb-3">
              <p className="max-w-[62ch] text-[14.5px] leading-relaxed">{run.data.report.situation}</p>
              <Chips items={run.data.report.focus} className="mt-3" />
            </div>

            {run.data.report.moves.map((move, i) => (
              <MoveRow key={`${move.player}-${i}`} move={move} />
            ))}

            {run.data.report.moves.length === 0 && (
              <p className="border-t border-border px-4 py-6 text-center text-[13.5px] text-muted-foreground">
                No moves worth making this week.
              </p>
            )}

            <div className="m-4 rounded-md border border-accent-foreground/25 bg-accent-foreground/8 px-3.5 py-2.5 text-[14px] leading-relaxed">
              {run.data.report.strategy}
            </div>
          </Card>

          <Chat chatId={run.data.chat_id} />
        </div>
      )}

      {standing.data && !run.isPending && (
        <div className="flex flex-col gap-4 px-5 pb-5 pt-4">
          <LineupCard
            title={run.data ? "As it stands" : "Your lineup"}
            lineup={standing.data.lineup}
            bench={standing.data.bench}
            swaps={standing.data.swaps}
          />
          {ai && !run.data && !run.isError && (
            <p className="max-w-[70ch] text-[13.5px] leading-relaxed text-muted-foreground">
              Everything above is read or computed from league state. Running a report adds the
              judgement — which projections to believe, which matchups to discount, what to do.
            </p>
          )}
        </div>
      )}
    </>
  );
}
