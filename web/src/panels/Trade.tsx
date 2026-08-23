import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { api, type Evaluation, type League, type Sport } from "@/lib/api";
import { verdictTone } from "@/lib/tone";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Chat, Chips, ErrorNote, PageHeader } from "@/panels/shared";

export function TradePanel({ sport, league, mock }: { sport: Sport; league: League; mock: boolean }) {
  const [text, setText] = useState("");

  const run = useMutation<Evaluation, Error, string>({
    mutationFn: (description) => api.trade(sport.sport, league.league_id, description, mock),
  });

  return (
    <>
      <PageHeader title="Trade evaluation" meta={league.name} />

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (text.trim()) run.mutate(text.trim());
        }}
        className="flex flex-wrap gap-2 border-b border-border px-5 py-4"
      >
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Give Bijan Robinson, Get Puka Nacua"
          className="h-9 min-w-0 flex-1 rounded-md border border-input bg-background px-3 text-[13.5px] placeholder:text-muted-foreground"
        />
        <Button type="submit" variant="primary" disabled={!text.trim() || run.isPending}>
          {run.isPending ? "Evaluating…" : "Evaluate"}
        </Button>
      </form>

      {run.isError && <ErrorNote error={run.error} />}
      {run.isPending && <Skeleton className="m-5 h-64" />}

      {run.data && (
        <div className="flex flex-col gap-4 p-5">
          <Card>
            <CardHeader>
              <span>Verdict</span>
            </CardHeader>
            <div className="flex flex-col gap-3 p-4">
              <div className="flex flex-wrap items-center gap-3">
                <span className="font-display text-3xl font-bold tracking-tight">{run.data.verdict.verdict}</span>
                <Badge variant={verdictTone(run.data.verdict.verdict)} appearance="status">
                  {sport.label.replace(/\s*\(.*\)$/, "")}
                </Badge>
              </div>
              <p className="max-w-[62ch] text-[14.5px] leading-relaxed">{run.data.verdict.verdict_detail}</p>

              <div className="mt-1 grid gap-4 sm:grid-cols-2">
                <Ledger label="Gains" items={run.data.verdict.gains} />
                <Ledger label="Losses" items={run.data.verdict.losses} />
              </div>
            </div>

            {(
              [
                ["Impact", run.data.verdict.impact],
                ["Schedule", run.data.verdict.schedule],
                ["Risk", run.data.verdict.risk],
                ["Strategy", run.data.verdict.strategy],
              ] as const
            ).map(([label, body]) => (
              <div key={label} className="border-t border-border px-4 py-3">
                <div className="font-mono text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                  {label}
                </div>
                <p className="mt-1 max-w-[62ch] text-[13.5px] leading-relaxed">{body}</p>
              </div>
            ))}
          </Card>

          <Chat chatId={run.data.chat_id} />
        </div>
      )}
    </>
  );
}

function Ledger({ label, items }: { label: string; items: string[] }) {
  return (
    <div>
      <div className="font-mono text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
        {label}
      </div>
      {items.length ? (
        <Chips items={items} className="mt-1.5" />
      ) : (
        <p className="mt-1.5 text-[13px] text-muted-foreground">—</p>
      )}
    </div>
  );
}
