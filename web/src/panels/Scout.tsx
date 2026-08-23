import { useMutation } from "@tanstack/react-query";
import { api, type Analysis, type League, type Sport } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Chat, Chips, ErrorNote, MoveRow, PageHeader } from "@/panels/shared";

export function ScoutPanel({ sport, league, mock }: { sport: Sport; league: League; mock: boolean }) {
  const run = useMutation<Analysis, Error>({
    mutationFn: () => api.scout(sport.sport, league.league_id, mock),
  });

  return (
    <>
      <PageHeader title={`${league.name} report`} meta={league.detail}>
        <Button variant="primary" onClick={() => run.mutate()} disabled={run.isPending}>
          {run.isPending ? "Building…" : run.data ? "Run again" : "Run report"}
        </Button>
      </PageHeader>

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

      {!run.data && !run.isPending && !run.isError && (
        <p className="p-5 text-[13.5px] text-muted-foreground">
          Reads live league state, computes what has an exact answer, and asks the model only for judgement.
          {mock && " Mock AI is on: the league data is real, the report is canned."}
        </p>
      )}
    </>
  );
}
