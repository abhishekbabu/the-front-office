import { useEffect, useMemo } from "react";
import { matchPath, useLocation, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Moon, Settings, Sun, Trophy } from "lucide-react";
import { AnimatePresence, m } from "motion/react";
import { api, type League, type Competition } from "@/lib/api";
import { useTheme } from "@/lib/useTheme";
import { IconButton } from "@/components/ui/icon-button";
import { Tooltip } from "@/components/ui/tooltip";
import { rise } from "@/lib/motion";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { ScoutPanel } from "@/panels/Scout";
import { LeaguePanel } from "@/panels/LeaguePanel";
import { FreeAgentsPanel } from "@/panels/FreeAgents";
import { ReportPanel } from "@/panels/Report";
import { TeamPanel } from "@/panels/Team";
import { TradePanel } from "@/panels/Trade";
import { SettingsPanel } from "@/panels/Settings";
import { Landing } from "@/panels/Landing";
import { cn } from "@/lib/utils";

/** The views that need a sport and a league behind them. */
/**
 * The views a competition has, and the slugs they are addressed by.
 *
 * One vocabulary rather than two: the id in the code is the word in the URL,
 * so there is no table mapping "scout" to "week" for somebody to get wrong.
 */
type SportView = "week" | "league" | "team" | "free-agents" | "report" | "trade";

/** What a league opens on, and what an unrecognised view falls back to. */
const DEFAULT_VIEW: SportView = "week";

/** Settings works with nothing configured, which is exactly when it is needed. */
export default function App() {
  const { mode, setMode } = useTheme();
  const navigate = useNavigate();
  const path = useLocation().pathname;
  // Every page is a URL, so a view can be linked, bookmarked and reloaded, and
  // Back means what it says. The shape is /{competition}/{league}/{view}, with
  // the default view left off so the short link and the long one are one page.
  // Matched by hand rather than rendered through <Routes>: the shell is one
  // layout whose rail and panel both read the same three values, so routing
  // here is reading the address, not choosing which subtree to render.
  const params = matchPath("/:competition/:league/:view?", path)?.params;
  const settings = path === "/settings";
  // A competition on its own is a real place to arrive — the rail links there,
  // and so does anybody who trims a URL — but it is not addressable until a
  // league is chosen, so it resolves to the first one below. Settings is
  // excluded by name: a one-segment path is otherwise indistinguishable from a
  // competition, and it would resolve to a league and bounce off this page.
  const bare = settings ? undefined : matchPath("/:competition", path)?.params;

  const sport = params?.competition ?? bare?.competition ?? null;
  const leagueId = params?.league ?? null;
  const view = (params?.view as SportView | undefined) ?? DEFAULT_VIEW;

  const openLeague = (competition: string, id: string, next: SportView = DEFAULT_VIEW, replace = false) =>
    navigate(next === DEFAULT_VIEW ? `/${competition}/${id}` : `/${competition}/${id}/${next}`, { replace });

  const sports = useQuery({ queryKey: ["sports"], queryFn: api.sports });
  // Without a model there is no analysis to give, so the views that produce one
  // are not offered at all. Adding a key makes them appear; nothing explains
  // their absence, because from the outside there is nothing missing.
  const capabilities = useQuery({ queryKey: ["capabilities"], queryFn: api.capabilities });

  // An error deep in a panel can send someone to Settings without every panel
  // needing to know the shell exists.
  useEffect(() => {
    const open = () => navigate("/settings");
    window.addEventListener("tfo:settings", open);
    return () => window.removeEventListener("tfo:settings", open);
  }, [navigate]);
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
  const active: Competition | undefined = usable.find((s) => s.key === sport);

  const leagues = useQuery({
    queryKey: ["leagues", active?.key],
    queryFn: () => api.leagues(active!.key),
    enabled: Boolean(active),
  });
  const league: League | undefined = (leagues.data ?? []).find((l) => l.league_id === leagueId) ?? leagues.data?.[0];

  // A sport that cannot trade must not leave the tab selected behind it.
  const panelKey = `${active?.key}:${league?.league_id}`;
  const views: SportView[] = [
    "week",
    "league",
    "team",
    "free-agents",
    // Both need a model, so neither is offered without one.
    ...(ai ? (["report"] as const) : []),
    ...(ai && active?.supports_trades ? (["trade"] as const) : []),
  ];
  const current: SportView = views.find((v) => v === view) ?? DEFAULT_VIEW;

  // Put the resolved league in the URL, so what is on screen is what the
  // address bar says and a reload lands in the same place. Replaced rather
  // than pushed: arriving at a competition and resolving its first league is
  // a correction, not a move, and pushing it would make Back bounce here again.
  useEffect(() => {
    // A competition nobody can play — a typo, or one whose credentials have
    // since gone — has no shell to render, so the address goes back to the
    // page that lists what there is. Only once the list has actually arrived:
    // before that every competition looks equally unavailable.
    if (sport && sports.data && !active) navigate("/", { replace: true });
    else if (sport && league && league.league_id !== leagueId) {
      openLeague(sport, league.league_id, current, true);
    }
  }, [sport, sports.data, active, league, leagueId, current, navigate]);

  return (
    // Fixed to the viewport, with each column scrolling on its own. A single
    // page scroll takes the rail with it, so the sport you are on and the way
    // back leave the screen exactly when a long table makes you want them.
    <div className="grid h-full grid-cols-[13rem_minmax(0,1fr)] overflow-hidden">
      <nav className="flex flex-col gap-6 overflow-y-auto border-r border-border bg-card px-3 py-4">
        <button
          onClick={() => navigate("/")}
          aria-label="Back to all leagues"
          className="flex items-center gap-2.5 rounded-md px-1 py-1 text-left transition-colors hover:bg-muted"
        >
          <span className="flex size-6 shrink-0 items-center justify-center rounded-sm bg-primary text-primary-foreground">
            <Trophy className="size-3.5" strokeWidth={2.25} aria-hidden />
          </span>
          <span className="font-display text-[15px] font-semibold tracking-tight">The Front Office</span>
        </button>

        {/* Competition, not sport: these are the NBA, the NFL and the Premier
            League. "League" is taken by the group below, which holds the
            fantasy leagues you actually play in. */}
        <Group label="Competition">
          {sports.isLoading && <Skeleton className="mx-2 h-7" />}
          {(sports.data ?? []).map((s) => (
            <RailItem
              key={s.key}
              active={s.key === active?.key}
              disabled={!s.ready}
              tooltip={
                s.ready ? "" : s.configured ? s.blocked_reason : `Not configured — set ${s.requires} in .env`
              }
              onClick={() => navigate(`/${s.key}`)}
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
              <RailItem key={v} active={v === current} onClick={() => sport && leagueId && openLeague(sport, leagueId, v)}>
                {
                  {
                    week: "This week",
                    league: "League",
                    team: "My team",
                    "free-agents": "Free agents",
                    report: "Report",
                    trade: "Trade",
                  }[v]
                }
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
                onClick={() => sport && openLeague(sport, l.league_id, current)}
              >
                <span className="truncate">{l.name}</span>
              </RailItem>
            ))}
          </Group>
        )}

        <div className="mt-auto flex flex-col gap-2">
          <div className="flex items-center gap-1">
            <RailItem className="flex-1" active={settings} onClick={() => navigate("/settings")}>
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
        {/* One presence around the whole column, keyed on the view. Settings is
            a place you go and come back from, so it earns the same in-and-out
            as everything else — previously it swapped in with no transition at
            all because it sat outside the only AnimatePresence here. */}
        <AnimatePresence mode="wait">
        <m.div key={settings ? "settings" : "app"} variants={rise} initial="hidden" animate="shown" exit="gone">
        {settings ? (
          <SettingsPanel onBack={() => navigate(sport && leagueId ? `/${sport}/${leagueId}` : "/")} />
        ) : sports.isSuccess && usable.length === 0 ? (
          <Empty sports={sports.data} />
        ) : !sport ? (
          sports.isSuccess ? (
            <Landing
              sports={sports.data}
              onPick={(picked, picked_league) => openLeague(picked.key, picked_league.league_id)}
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
              {current === "week" ? (
                <ScoutPanel sport={active} league={league} />
              ) : current === "league" ? (
                <LeaguePanel sport={active} league={league} />
              ) : current === "team" ? (
                <TeamPanel sport={active} league={league} />
              ) : current === "free-agents" ? (
                <FreeAgentsPanel sport={active} league={league} />
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
        </m.div>
        </AnimatePresence>
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
function Empty({ sports }: { sports: Competition[] }) {
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
