import { cn } from "@/lib/utils";
import type { Stat as StatValue } from "@/lib/api";

/**
 * The strip under a page title: where the team stands, before any reading.
 *
 * Every figure is computed by the provider from live league state, never
 * written by the model, so these can be read as fact. `tone` is what lets one
 * of them leave the row — a warning here always means a decision still open.
 */
export function StatStrip({ stats }: { stats: StatValue[] }) {
  if (!stats.length) return null;
  return (
    <div className="flex flex-wrap border-b border-border">
      {stats.map((stat) => (
        <div
          key={stat.label}
          // Not on the last: a divider with nothing after it reads as an empty
          // cell stretching to the edge.
          className="min-w-[7rem] border-border px-5 py-2.5 [&:not(:last-child)]:border-r"
        >
          <div className="font-mono text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
            {stat.label}
          </div>
          <div
            className={cn(
              "mt-0.5 font-display text-[19px] font-semibold tracking-tight tabular-nums",
              stat.tone === "good" && "text-ok",
              stat.tone === "warning" && "text-warn",
            )}
          >
            {stat.value}
          </div>
        </div>
      ))}
    </div>
  );
}
