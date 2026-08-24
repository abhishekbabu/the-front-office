import { useMutation } from "@tanstack/react-query";
import { api, type Analysis, type League, type Competition } from "@/lib/api";
import { Play, RotateCw } from "lucide-react";
import { IconButton } from "@/components/ui/icon-button";
import { Empty, Working } from "@/components/ui/state";
import { Card, CardHeader } from "@/components/ui/card";
import { Chat, Chips, ErrorNote, MoveRow, PageHeader } from "@/panels/shared";

/**
 * The analysis, on its own.
 *
 * Split from the week because the two answer different questions and are read
 * at different moments: the week is a glance before a deadline, this is a
 * considered opinion that costs a model call to produce.
 */
export function ReportPanel({ sport, league }: { sport: Competition; league: League }) {
  const run = useMutation<Analysis, Error>({
    mutationFn: () => api.scout(sport.key, league.league_id),
  });

  return (
    <>
      <PageHeader title="Report" meta={league.name}>
        <IconButton
          label={run.isPending ? "Building the report" : run.data ? "Run again" : "Run report"}
          variant="primary"
          icon={run.data ? <RotateCw /> : <Play />}
          onClick={() => run.mutate()}
          disabled={run.isPending}
        />
      </PageHeader>

      {run.isError && <ErrorNote error={run.error} />}

      {/* A spinner rather than a placeholder: this is work someone started and
          is waiting on, and a skeleton implies something is already arriving. */}
      {run.isPending && <Working label="Reading the league, then asking the model…" />}

      {!run.data && !run.isPending && !run.isError && (
        <Empty
          title="No report yet"
          detail="Reads your league as it stands, works out what has an exact answer — the best legal lineup, what a transfer costs, how many games are left — and asks the model only for the judgement."
        />
      )}

      {run.data && (
        <div className="flex flex-col gap-4 p-5">
          <Card>
            <CardHeader>
              <span>What this week turns on</span>
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
    </>
  );
}
