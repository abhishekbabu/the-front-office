import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import type { Spot, Swap } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * The team as it currently stands, and what the numbers say to change.
 *
 * Everything here is read or computed from league state, so it is on the page
 * before a report is asked for — and once one arrives it is the thing the
 * report is arguing about.
 */
export function LineupCard({
  title,
  lineup,
  bench,
  swaps,
}: {
  title: string;
  lineup: Spot[];
  bench: Spot[];
  swaps: Swap[];
}) {
  if (!lineup.length && !bench.length) return null;
  return (
    <Card>
      <CardHeader>
        <span>{title}</span>
        <span>{lineup.length} starting</span>
      </CardHeader>

      <div className="grid grid-cols-1 md:grid-cols-2">
        <SpotList spots={lineup} />
        <div className="border-t border-border md:border-l md:border-t-0">
          <div className="border-b border-border px-4 py-2 font-mono text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
            Bench
          </div>
          <SpotList spots={bench} empty="Nobody on the bench." />
        </div>
      </div>

      {swaps.length > 0 && (
        <div className="border-t border-border">
          <div className="px-4 pb-1 pt-3 font-mono text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
            Changes the projections imply
          </div>
          {/* Exact, not suggested: the report's job is to endorse or overrule
              these, not to discover them. */}
          {swaps.map((swap) => (
            <div key={swap.start} className="flex flex-wrap items-baseline gap-x-2 gap-y-1 px-4 py-2 text-[13px]">
              <span className="font-medium">{swap.start}</span>
              <span className="text-muted-foreground">for {swap.out || "an empty place"}</span>
              <span className="ml-auto font-mono text-[12px] text-ok">{swap.gain}</span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

function SpotList({ spots, empty }: { spots: Spot[]; empty?: string }) {
  if (!spots.length) {
    return <p className="px-4 py-3 text-[13px] text-muted-foreground">{empty ?? "Nothing set."}</p>;
  }
  return (
    <div className="flex flex-col">
      {spots.map((spot, i) => (
        <div
          key={`${spot.player}-${i}`}
          className="flex items-baseline gap-3 border-b border-border/45 px-4 py-2 last:border-b-0"
        >
          {spot.slot && (
            <span className="w-16 shrink-0 font-mono text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
              {spot.slot}
            </span>
          )}
          <div className="min-w-0 flex-1">
            <div className="truncate text-[13.5px] font-medium">{spot.player}</div>
            <div className="truncate font-mono text-[11px] text-muted-foreground">{spot.detail}</div>
          </div>
          {spot.tone === "warning" ? (
            <Badge variant="warn" appearance="pill" className="tabular-nums">
              {spot.value}
            </Badge>
          ) : (
            <span className={cn("shrink-0 font-mono text-[12.5px] tabular-nums")}>{spot.value}</span>
          )}
        </div>
      ))}
    </div>
  );
}
