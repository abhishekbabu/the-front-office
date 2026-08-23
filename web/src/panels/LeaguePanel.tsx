import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { m } from "motion/react";
import { api, type League, type LeagueSchedule, type Sport } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { Empty, Loading } from "@/components/ui/state";
import { ErrorNote, PageHeader } from "@/panels/shared";
import { list, listItem, rise } from "@/lib/motion";
import { cn } from "@/lib/utils";

/**
 * The league beyond this week.
 *
 * Four questions that are all "how is the season going" rather than "what do I
 * do about Sunday", which is what the week view is for. They are tabs rather
 * than four cards down one page because they are read one at a time — you come
 * here to check the table, or to see what you missed, not both.
 */
type TabId = "season" | "standings" | "matches" | "activity";

const TABS: { id: TabId; label: string }[] = [
  { id: "season", label: "Season" },
  { id: "standings", label: "Table" },
  { id: "matches", label: "Fixtures" },
  { id: "activity", label: "Activity" },
];

export function LeaguePanel({ sport, league }: { sport: Sport; league: League }) {
  const schedule = useQuery<LeagueSchedule, Error>({
    queryKey: ["schedule", sport.key, league.league_id],
    queryFn: () => api.schedule(sport.key, league.league_id),
  });

  // Only the sections this platform actually answers. A tab that is always
  // empty is worse than one that is not there: FPL publishes no transfer feed,
  // and a category league has no fixture list.
  const available = TABS.filter((tab) => (schedule.data?.[tab.id]?.length ?? 0) > 0);
  const [tab, setTab] = useState<TabId>("season");
  const current = available.find((t) => t.id === tab)?.id ?? available[0]?.id;

  return (
    <>
      <PageHeader title={league.name} meta={league.detail}>
        {available.length > 1 && (
          <div className="flex items-center gap-1" role="tablist">
            {available.map((t) => (
              <button
                key={t.id}
                role="tab"
                aria-selected={t.id === current}
                onClick={() => setTab(t.id)}
                className={cn(
                  "rounded-md px-3 py-1.5 text-[13px] font-medium transition-colors",
                  t.id === current ? "bg-secondary text-foreground" : "text-muted-foreground hover:bg-muted",
                )}
              >
                {t.label}
              </button>
            ))}
          </div>
        )}
      </PageHeader>

      {schedule.isLoading && <Loading lines={6} />}
      {schedule.isError && <ErrorNote error={schedule.error} />}

      {schedule.data && !current && (
        <Empty
          title="Nothing beyond this week"
          detail="This platform publishes no season, table or fixture list through its API."
        />
      )}

      {schedule.data && current && (
        <m.div key={current} variants={rise} initial="hidden" animate="shown" className="p-5">
          {current === "season" && <Season rows={schedule.data.season} />}
          {current === "standings" && <Standings rows={schedule.data.standings} />}
          {current === "matches" && <Matches rows={schedule.data.matches} />}
          {current === "activity" && <Activity rows={schedule.data.activity} />}
        </m.div>
      )}
    </>
  );
}

/**
 * One row, with the one that is yours marked.
 *
 * A tint alone will not do it: `muted` is a hair off the card in light mode,
 * and a reader who cannot see the hue gets no marker at all. The rule here is
 * the same as everywhere else in this app — state carried in color is also
 * carried in shape, so the row keeps a solid rule down its left edge.
 */
function Row({ children, current, className }: { children: React.ReactNode; current?: boolean; className?: string }) {
  return (
    <m.div
      variants={listItem}
      className={cn(
        "flex items-baseline gap-3 border-t border-border py-2.5 pr-4 text-[13px] first:border-t-0",
        current ? "border-l-2 border-l-foreground bg-muted pl-[calc(1rem-2px)]" : "pl-4",
        className,
      )}
    >
      {children}
    </m.div>
  );
}

function Section({ title, count, children }: { title: string; count: string; children: React.ReactNode }) {
  return (
    <Card>
      <CardHeader>
        <span>{title}</span>
        <span>{count}</span>
      </CardHeader>
      <m.div variants={list} initial="hidden" animate="shown" className="flex flex-col">
        {children}
      </m.div>
    </Card>
  );
}

function Season({ rows }: { rows: LeagueSchedule["season"] }) {
  return (
    <Section title="Your season" count={`${rows.length} weeks`}>
      {rows.map((row) => (
        <Row key={row.label} current={row.is_current}>
          <span className="w-24 shrink-0 font-mono text-[11px] uppercase tracking-[0.06em] text-muted-foreground">
            {row.label}
          </span>
          <span className="w-32 shrink-0 font-mono text-[11px] text-muted-foreground">{row.date}</span>
          <span className="min-w-0 flex-1 truncate">
            {row.opponent || <span className="text-muted-foreground">{row.detail || "—"}</span>}
          </span>
          {/* Said, not only shaded — the tint is reinforcement. */}
          {row.is_current && (
            <Badge variant="muted" appearance="label" className="shrink-0">
              this week
            </Badge>
          )}
          {row.opponent && row.detail && (
            <span className="shrink-0 font-mono text-[11px] text-muted-foreground">{row.detail}</span>
          )}
          {/* Won and lost are carried by the word as well as the color: state
              in color alone is state a colorblind reader cannot see. */}
          {row.result && (
            <Badge
              variant={row.tone === "good" ? "ok" : row.tone === "warning" ? "fail" : "muted"}
              appearance="pill"
              className="tabular-nums"
            >
              {row.tone === "good" ? "W" : row.tone === "warning" ? "L" : "D"} {row.result}
            </Badge>
          )}
        </Row>
      ))}
    </Section>
  );
}

function Standings({ rows }: { rows: LeagueSchedule["standings"] }) {
  return (
    <Section title="Table" count={`${rows.length} teams`}>
      {rows.map((row) => (
        <Row key={`${row.rank}-${row.name}`} current={row.is_mine}>
          <span className="w-6 shrink-0 text-right font-mono text-[12px] tabular-nums text-muted-foreground">
            {row.rank}
          </span>
          <span className={cn("min-w-0 flex-1 truncate", row.is_mine && "font-semibold")}>{row.name}</span>
          {row.is_mine && (
            <Badge variant="muted" appearance="label" className="shrink-0">
              you
            </Badge>
          )}
          {row.detail && (
            <span className="hidden shrink-0 truncate font-mono text-[11px] text-muted-foreground sm:block">
              {row.detail}
            </span>
          )}
          {row.record && <span className="shrink-0 font-mono text-[11.5px] tabular-nums">{row.record}</span>}
          <span className="w-28 shrink-0 text-right font-mono text-[12px] tabular-nums">{row.points}</span>
        </Row>
      ))}
    </Section>
  );
}

function Matches({ rows }: { rows: LeagueSchedule["matches"] }) {
  return (
    <Section title="This week's fixtures" count={`${rows.length} matches`}>
      {rows.map((row, i) => (
        <Row key={`${row.home}-${row.away}-${i}`}>
          <span className="w-36 shrink-0 font-mono text-[11px] text-muted-foreground">{row.label}</span>
          <span className="min-w-0 flex-1 font-mono text-[12.5px]">
            {row.away} <span className="text-muted-foreground">at</span> {row.home}
          </span>
          {row.detail && (
            <span className={cn("shrink-0 font-mono text-[11px]", row.tone === "warning" ? "text-warn" : "text-muted-foreground")}>
              {row.detail}
            </span>
          )}
        </Row>
      ))}
    </Section>
  );
}

function Activity({ rows }: { rows: LeagueSchedule["activity"] }) {
  return (
    <Section title="Recent activity" count={`${rows.length} moves`}>
      {rows.map((row, i) => (
        <Row key={`${row.when}-${i}`} current={row.tone === "good"}>
          <span className="w-16 shrink-0 font-mono text-[11px] text-muted-foreground">{row.when}</span>
          <span className="w-32 shrink-0 truncate">{row.who}</span>
          <Badge variant="muted" appearance="label" className="shrink-0">
            {row.what}
          </Badge>
          <span className="min-w-0 flex-1 truncate font-mono text-[11.5px] text-muted-foreground">{row.detail}</span>
        </Row>
      ))}
    </Section>
  );
}
