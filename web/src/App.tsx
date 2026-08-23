import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Moon, Settings, Sun, Trophy } from "lucide-react";
import { AnimatePresence, m } from "motion/react";
import { api, type League, type Sport } from "@/lib/api";
import { useTheme } from "@/lib/useTheme";
import { IconButton } from "@/components/ui/icon-button";
import { Tooltip } from "@/components/ui/tooltip";
import { rise } from "@/lib/motion";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { ScoutPanel } from "@/panels/Scout";
import { ReportPanel } from "@/panels/Report";
import { TeamPanel } from "@/panels/Team";
import { TradePanel } from "@/panels/Trade";
import { SettingsPanel } from "@/panels/Settings";
import { Landing } from "@/panels/Landing";
import { cn } from "@/lib/utils";

/** The views that need a sport and a league behind them. */
type SportView = "scout" | "team" | "report" | "trade";

/** Settings works with nothing configured, which is exactly when it is needed. */
type View = SportView | "settings" | "home";

export default function App() {
  const { mode, setMode } = useTheme();
  const [sport, setSport] = useState<string | null>(null);
  const [view, setView] = useState<View>("home");
  const [leagueId, setLeagueId] = useState<string | null>(null);

  const sports = useQuery({ queryKey: ["sports"], queryFn: api.sports });
  // Without a model there is no analysis to give, so the views that produce one
  // are not offered at all. Adding a key makes them appear; nothing explains
  // their absence, because from the outside there is nothing missing.
  const capabilities = useQuery({ queryKey: ["capabilities"], queryFn: api.capabilities });

  // An error deep in a panel can send someone to Settings without every panel
  // needing to know the shell exists.
  useEffect(() => {
    const open = () => setView("settings");
    window.addEventListener("tfo:settings", open);
    return () => window.removeEventListener("tfo:settings", open);
  }, []);
  const ai = capabilities.data?.ai ?? false;

  // How many platforms carry each sport, so the rail shows the platform only
  // where it distinguishes something.
  const sportCounts = (sports.data ?? []).reduce<Record<string, number>>((counts, s) => {
    counts[s.sport] = (counts[s.sport] ?? 0) + 1;
    return counts;
  }, {});
  // Ready, not merely configured: credentials being set says nothing about
  // whether a platform will actually answer.
  const usable = useMemo(() => (sports.data ?? []).filter((s) => s.ready), [sports.data]);
  // No fallback to the first configured sport: until one is chosen the landing
  // page is what shows, and choosing for the user is what it exists to avoid.
  const active: Sport | undefined = usable.find((s) => s.key === sport);

  const leagues = useQuery({
    queryKey: ["leagues", active?.key],
    queryFn: () => api.leagues(active!.key),
    enabled: Boolean(active),
  });
  const league: League | undefined = (leagues.data ?? []).find((l) => l.league_id === leagueId) ?? leagues.data?.[0];

  // A sport that cannot trade must not leave the tab selected behind it.
  const panelKey = `${active?.key}:${league?.league_id}`;
  const views: SportView[] = [
    "scout",
    "team",
    // Both need a model, so neither is offered without one.
    ...(ai ? (["report"] as const) : []),
    ...(ai && active?.supports_trades ? (["trade"] as const) : []),
  ];
  const current: SportView = views.find((v) => v === view) ?? "scout";

  return (
    // Fixed to the viewport, with each column scrolling on its own. A single
    // page scroll takes the rail with it, so the sport you are on and the way
    // back leave the screen exactly when a long table makes you want them.
    <div className="grid h-full grid-cols-[13rem_minmax(0,1fr)] overflow-hidden">
      <nav className="flex flex-col gap-6 overflow-y-auto border-r border-border bg-card px-3 py-4">
        <button
          onClick={() => setView("home")}
          aria-label="Back to all leagues"
          className="flex items-center gap-2.5 rounded-md px-1 py-1 text-left transition-colors hover:bg-muted"
        >
          <span className="flex size-6 shrink-0 items-center justify-center rounded-sm bg-primary text-primary-foreground">
            <Trophy className="size-3.5" strokeWidth={2.25} aria-hidden />
          </span>
          <span className="font-display text-[15px] font-semibold tracking-tight">The Front Office</span>
        </button>

        <Group label="Sport">
          {sports.isLoading && <Skeleton className="mx-2 h-7" />}
          {(sports.data ?? []).map((s) => (
            <RailItem
              key={s.key}
              active={s.key === active?.key}
              disabled={!s.ready}
              tooltip={
                s.ready ? "" : s.configured ? s.blocked_reason : `Not configured — set ${s.requires} in .env`
              }
              onClick={() => {
                setSport(s.key);
                setLeagueId(null);
                if (view === "home") setView("scout");
              }}
            >
              {/* Two platforms under one sport need telling apart; one does not. */}
              {(sportCounts[s.sport] ?? 0) > 1 ? s.label : s.label.replace(/\s*\(.*\)$/, "")}
              {!s.ready && (
                <span className="font-mono text-[10px] opacity-60">{s.configured ? "blocked" : "off"}</span>
              )}
            </RailItem>
          ))}
        </Group>

        {active && (
          <Group label="View">
            {views.map((v) => (
              <RailItem key={v} active={v === current} onClick={() => setView(v)}>
                {{ scout: "This week", team: "My team", report: "Report", trade: "Trade" }[v]}
              </RailItem>
            ))}
          </Group>
        )}

        {(leagues.data?.length ?? 0) > 1 && (
          <Group label="League">
            {leagues.data!.map((l) => (
              <RailItem
                key={l.league_id}
                active={l.league_id === league?.league_id}
                onClick={() => setLeagueId(l.league_id)}
              >
                <span className="truncate">{l.name}</span>
              </RailItem>
            ))}
          </Group>
        )}

        <div className="mt-auto flex flex-col gap-2">
          <div className="flex items-center gap-1">
            <RailItem className="flex-1" active={view === "settings"} onClick={() => setView("settings")}>
              <span className="flex items-center gap-2">
                <Settings className="size-3.5" aria-hidden />
                Settings
              </span>
            </RailItem>
            <IconButton
              label={mode === "dark" ? "Switch to light" : "Switch to dark"}
              side="top"
              icon={mode === "dark" ? <Sun /> : <Moon />}
              onClick={() => setMode(mode === "dark" ? "light" : "dark")}
            />
          </div>
        </div>
      </nav>

      <main className="min-w-0 overflow-y-auto">
        {/* Keyed on the view so switching one animates the new panel in;
            without a key React reuses the tree and nothing transitions. */}
        {view === "settings" ? (
          <SettingsPanel onBack={() => setView(sport ? "scout" : "home")} />
        ) : sports.isSuccess && usable.length === 0 ? (
          <Empty sports={sports.data} />
        ) : view === "home" ? (
          sports.isSuccess ? (
            <Landing
              sports={sports.data}
              onPick={(picked, picked_league) => {
                setSport(picked.key);
                setLeagueId(picked_league.league_id);
                setView("scout");
              }}
            />
          ) : (
            <div className="p-6">
              <Skeleton className="h-40 w-full" />
            </div>
          )
        ) : active && league ? (
          // Keyed so a sport or league change remounts the panel. Without it the
          // panel keeps the report it already fetched, and the previous sport's
          // analysis renders under the new league's name — a stale FPL report
          // headed "Huge Euge RR FF", with FPL's figures in the strip.
          <AnimatePresence mode="wait">
            <m.div key={`${panelKey}:${current}`} variants={rise} initial="hidden" animate="shown">
              {current === "scout" ? (
                <ScoutPanel sport={active} league={league} />
              ) : current === "team" ? (
                <TeamPanel sport={active} league={league} />
              ) : current === "report" ? (
                <ReportPanel sport={active} league={league} />
              ) : (
                <TradePanel sport={active} league={league} />
              )}
            </m.div>
          </AnimatePresence>
        ) : (
          <div className="p-6">
            {leagues.isError ? (
              <Badge variant="fail" appearance="status">
                {(leagues.error as Error).message}
              </Badge>
            ) : (
              <Skeleton className="h-40 w-full" />
            )}
          </div>
        )}
      </main>
    </div>
  );
}

function Group({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <p className="px-2 pb-1.5 font-mono text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
        {label}
      </p>
      {children}
    </div>
  );
}

function RailItem({
  active,
  disabled,
  className,
  tooltip,
  children,
  ...props
}: React.ComponentProps<"button"> & { active?: boolean; tooltip?: string }) {
  const button = (
    <button
      disabled={disabled}
      className={cn(
        "flex items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-[13.5px] transition-colors",
        active ? "bg-accent font-medium text-accent-foreground" : "text-muted-foreground hover:bg-muted",
        disabled && "cursor-not-allowed opacity-40 hover:bg-transparent",
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
  // A disabled control cannot be hovered in every browser, so the reason is
  // wrapped rather than attached — and Radix keeps it reachable by keyboard.
  return tooltip ? (
    <Tooltip label={tooltip} side="right">
      <span className={cn(disabled && "cursor-not-allowed")}>{button}</span>
    </Tooltip>
  ) : (
    button
  );
}

/** Nothing is configured — say what to set rather than showing an empty shell. */
function Empty({ sports }: { sports: Sport[] }) {
  return (
    <div className="mx-auto max-w-xl p-10">
      <h1 className="font-display text-2xl font-semibold tracking-tight">Nothing connected yet</h1>
      <p className="mt-2 text-sm text-muted-foreground">
        Set one of these in Settings, or in <code className="font-mono text-accent-foreground">.env</code> directly.
      </p>
      <ul className="mt-5 flex flex-col gap-2">
        {sports.map((s) => (
          <li key={s.sport} className="flex items-baseline justify-between gap-4 border-b border-border py-2 text-sm">
            <span>{s.label}</span>
            <code className="font-mono text-[12px] text-muted-foreground">{s.requires}</code>
          </li>
        ))}
      </ul>
    </div>
  );
}
