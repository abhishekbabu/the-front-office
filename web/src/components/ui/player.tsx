import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { api, type PlayerDetail } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/**
 * One player, opened from wherever their name appears.
 *
 * A panel rather than a page: you open it to settle a question about a row you
 * are already looking at, and closing it should put you back exactly there.
 */
export function PlayerPanel({
  sport,
  league,
  playerId,
  onClose,
}: {
  sport: string;
  league: string;
  playerId: string;
  onClose: () => void;
}) {
  const player = useQuery<PlayerDetail, Error>({
    queryKey: ["player", sport, league, playerId],
    queryFn: () => api.player(sport, league, playerId),
  });

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-foreground/20"
      onClick={onClose}
      role="presentation"
    >
      <aside
        className="flex h-full w-full max-w-md flex-col overflow-y-auto border-l border-border bg-popover shadow-lg"
        onClick={(e) => e.stopPropagation()}
        aria-label="Player detail"
      >
        <div className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
          <div className="min-w-0">
            {player.data ? (
              <>
                <h2 className="font-display text-xl font-semibold tracking-tight">{player.data.name}</h2>
                <p className="mt-0.5 font-mono text-[12px] text-muted-foreground">
                  {[player.data.position, player.data.team].filter(Boolean).join(" · ")}
                </p>
              </>
            ) : (
              <Skeleton className="h-6 w-40" />
            )}
          </div>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close">
            <X />
          </Button>
        </div>

        {player.isError && (
          <p className="m-5 text-[13.5px] leading-relaxed text-destructive">{player.error.message}</p>
        )}

        {player.data && (
          <div className="flex flex-col gap-5 px-5 py-4">
            <div>
              <div
                className={cn(
                  "font-display text-3xl font-semibold tracking-tight tabular-nums",
                  player.data.tone === "warning" && "text-warn",
                )}
              >
                {player.data.headline}
              </div>
              {player.data.note && (
                <Badge variant="warn" appearance="status" className="mt-2">
                  {player.data.note}
                </Badge>
              )}
            </div>

            <dl className="grid grid-cols-2 gap-x-4">
              {player.data.stats.map((stat) => (
                <div
                  key={stat.label}
                  className="flex items-baseline justify-between gap-3 border-b border-border/45 py-2"
                >
                  <dt className="font-mono text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
                    {stat.label}
                  </dt>
                  <dd className="font-mono text-[13px] tabular-nums">{stat.value}</dd>
                </div>
              ))}
            </dl>
          </div>
        )}
      </aside>
    </div>
  );
}
