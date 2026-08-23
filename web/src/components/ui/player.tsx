import { useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { X } from "lucide-react";
import { AnimatePresence, m } from "motion/react";
import { fade, list, listItem, slideOver } from "@/lib/motion";
import { IconButton } from "@/components/ui/icon-button";
import { ExternalLink } from "@/components/ui/external-link";
import { Loading } from "@/components/ui/state";
import { NOT_APPLICABLE, api, type PlayerDetail, type StatTable } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/**
 * One player, opened from wherever their name appears.
 *
 * A panel rather than a page: you open it to settle a question about a row you
 * are already looking at, and closing it should put you back exactly there.
 *
 * Mounted whether or not anyone is open — `playerId` of null is the closed
 * state, not a reason to render nothing. A caller that instead dropped the
 * component would take this AnimatePresence down with it, and an exit
 * animation cannot play from a tree that has already gone.
 */
/**
 * The one figure this player is judged on, beside their name.
 *
 * A figure gets display type; the absence of one gets a sentence. Setting
 * "no projection" at that size renders a missing number as though it were
 * the number.
 */
function Headline({ detail }: { detail: PlayerDetail }) {
  if (!detail.headline) {
    return detail.headline_label ? (
      <p className="mt-1.5 text-[13px] leading-snug text-muted-foreground">{detail.headline_label}</p>
    ) : null;
  }
  return (
    <div className="mt-1.5 flex items-baseline gap-2">
      <span
        className={cn(
          "font-display text-[28px] font-semibold leading-none tracking-tight tabular-nums",
          detail.tone === "warning" && "text-warn",
        )}
      >
        {detail.headline}
      </span>
      {detail.headline_label && (
        <span className="min-w-0 font-mono text-[11px] leading-snug text-muted-foreground">
          {detail.headline_label}
        </span>
      )}
    </div>
  );
}

/**
 * The same measures across several seasons, read across.
 *
 * The figures are the point, so they are right-aligned and tabular and the
 * column headings sit above them; the label column is the only thing on the
 * left. Scrolls inside itself rather than widening the drawer — three seasons
 * fit, and a fourth would not.
 */
function SeasonTable({ table }: { table: StatTable }) {
  return (
    <div className="overflow-x-auto rounded-md border border-border">
      <table className="w-full border-collapse text-[13px]">
        <thead>
          <tr className="border-b border-border">
            <th className="px-3 py-2 text-left font-mono text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              {/* The row labels need no heading; the seasons do. */}
            </th>
            {table.columns.map((column, i) => (
              <th
                key={column}
                className={cn(
                  "px-3 py-2 text-right font-mono text-[11px] font-semibold tabular-nums",
                  // The season in progress is the one being compared against,
                  // so it reads as the subject rather than another column.
                  i === 0 ? "text-foreground" : "text-muted-foreground",
                )}
              >
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row) => (
            <tr key={row.label} className="border-b border-border/45 last:border-b-0">
              <th
                scope="row"
                className="whitespace-nowrap px-3 py-1.5 text-left text-[13px] font-normal text-muted-foreground"
              >
                {row.label}
              </th>
              {row.values.map((value, i) => (
                <td
                  key={`${row.label}-${i}`}
                  className={cn(
                    "whitespace-nowrap px-3 py-1.5 text-right font-mono text-[12.5px] tabular-nums",
                    // Nothing to report reads as absence, not as a figure.
                    value === NOT_APPLICABLE && "text-muted-foreground/50",
                    row.tone === "good" && "text-ok",
                    row.tone === "warning" && "text-warn",
                  )}
                >
                  {value}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * A player's face, where the platform has one.
 *
 * Removed rather than replaced when it fails to load: the CDNs answer for
 * most players and 404 for the rest, and a broken-image glyph beside a name
 * looks like the app is broken rather than like the photo is missing.
 */
function Portrait({ src, name }: { src: string; name: string }) {
  const [failed, setFailed] = useState(false);
  if (!src || failed) return null;
  return (
    <m.img
      src={src}
      alt=""
      aria-hidden
      variants={fade}
      initial="hidden"
      animate="shown"
      onError={() => setFailed(true)}
      title={name}
      // Square and centre-cropped, which suits both: FPL ships a 500px square
      // cut-out, Sleeper a 350x254 studio card whose only loss to a square is
      // white margin. 96px is as large as the smaller of the two stays sharp
      // at 2x, so this is the size the sources actually support rather than
      // the size that would look boldest.
      className="size-24 shrink-0 rounded-lg bg-photo object-cover"
    />
  );
}

export function PlayerPanel({
  sport,
  league,
  playerId,
  onClose,
}: {
  sport: string;
  league: string;
  playerId: string | null;
  onClose: () => void;
}) {
  // Held so the panel still has someone to show on the way out. Reading
  // `playerId` directly would blank the contents for the length of the slide.
  const last = useRef("");
  if (playerId) last.current = playerId;
  const shown = playerId ?? last.current;

  const player = useQuery<PlayerDetail, Error>({
    queryKey: ["player", sport, league, shown],
    queryFn: () => api.player(sport, league, shown),
    enabled: Boolean(shown),
  });

  return (
    <AnimatePresence>
      {playerId && (
      <m.div
        variants={fade}
        initial="hidden"
        animate="shown"
        exit="gone"
        key="player-panel"
        className="fixed inset-0 z-50 flex justify-end bg-foreground/20"
        onClick={onClose}
        role="presentation"
      >
        <m.aside
          variants={slideOver}
          initial="hidden"
          animate="shown"
          exit="gone"
          // Wide enough that a season table fits without scrolling inside
          // itself — three columns of "£14.0m → £14.7m" is what sets the
          // floor. Still capped, and still full width on a narrow screen.
          className="flex h-full w-full max-w-2xl flex-col overflow-y-auto border-l border-border bg-popover shadow-lg"
          onClick={(e) => e.stopPropagation()}
          aria-label="Player detail"
        >
          {/* Everything that says who this is, pinned. On a long stat table
              the name and the one figure they are judged on are exactly what
              you stop being able to see, and they are what every row below is
              about. */}
          <div className="sticky top-0 z-10 flex items-start gap-4 border-b border-border bg-popover px-5 py-4">
            {player.data && <Portrait src={player.data.image_url} name={player.data.name} />}

            <div className="min-w-0 flex-1 pt-0.5">
              {player.data ? (
                <>
                  <h2 className="font-display text-[22px] font-semibold leading-tight tracking-tight">
                    {player.data.name}
                  </h2>
                  <p className="mt-1 font-mono text-[11px] uppercase tracking-[0.06em] text-muted-foreground">
                    {[player.data.position, player.data.team].filter(Boolean).join(" · ")}
                  </p>
                  <Headline detail={player.data} />
                  {player.data.note && (
                    <Badge variant="warn" appearance="status" className="mt-2">
                      {player.data.note}
                    </Badge>
                  )}
                </>
              ) : (
                <div className="flex flex-col gap-2">
                  <Skeleton className="h-6 w-44" />
                  <Skeleton className="h-3 w-24" />
                </div>
              )}
            </div>

            <div className="flex shrink-0 items-center">
              {player.data?.url && (
                <ExternalLink href={player.data.url} label={`Open ${player.data.name} on the platform`} />
              )}
              <IconButton label="Close" side="left" icon={<X />} onClick={onClose} />
            </div>
          </div>

          {player.isLoading && <Loading lines={4} />}
          {player.isError && (
            <p className="m-5 text-[13.5px] leading-relaxed text-destructive">{player.error.message}</p>
          )}

          {player.data && (
            <m.div variants={list} initial="hidden" animate="shown" className="flex flex-col gap-5 px-5 py-4">
              {player.data.tables.map((table) => (
                <m.section key={table.title} variants={listItem}>
                  <h3 className="mb-1.5 font-mono text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                    {table.title}
                  </h3>
                  <SeasonTable table={table} />
                </m.section>
              ))}

              {player.data.groups.map((group) => (
                <m.section key={group.title} variants={listItem}>
                  <h3 className="mb-1 font-mono text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                    {group.title}
                  </h3>
                  <dl>
                    {group.stats.map((stat) => (
                      <div
                        key={stat.label}
                        className="flex items-baseline justify-between gap-3 border-b border-border/45 py-1.5 last:border-b-0"
                      >
                        <dt className="text-[13px] text-muted-foreground">{stat.label}</dt>
                        <dd
                          className={cn(
                            "font-mono text-[13px] tabular-nums",
                            stat.tone === "good" && "text-ok",
                            stat.tone === "warning" && "text-warn",
                          )}
                        >
                          {stat.value}
                        </dd>
                      </div>
                    ))}
                  </dl>
                </m.section>
              ))}
            </m.div>
          )}
        </m.aside>
      </m.div>
      )}
    </AnimatePresence>
  );
}
