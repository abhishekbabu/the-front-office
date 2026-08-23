import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Moon, Settings, Sun, Trophy } from "lucide-react";
import { api, type League, type Sport } from "@/lib/api";
import { useTheme } from "@/lib/useTheme";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { ScoutPanel } from "@/panels/Scout";
import { TeamPanel } from "@/panels/Team";
import { TradePanel } from "@/panels/Trade";
import { SettingsPanel } from "@/panels/Settings";
import { Landing } from "@/panels/Landing";
import { cn } from "@/lib/utils";

/** The views that need a sport and a league behind them. */
type SportView = "scout" | "team" | "trade";

/** Settings works with nothing configured, which is exactly when it is needed. */
type View = SportView | "settings" | "home";

export default function App() {
  const { mode, setMode } = useTheme();
  const [sport, setSport] = useState<string | null>(null);
  const [view, setView] = useState<View>("home");
  const [leagueId, setLeagueId] = useState<string | null>(null);

  const sports = useQuery({ queryKey: ["sports"], queryFn: api.sports });
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const mockOn = (settings.data ?? []).some((s) => s.key === "MOCK_AI" && s.value === "true");
  const configured = useMemo(() => (sports.data ?? []).filter((s) => s.configured), [sports.data]);
  // No fallback to the first configured sport: until one is chosen the landing
  // page is what shows, and choosing for the user is what it exists to avoid.
  const active: Sport | undefined = configured.find((s) => s.sport === sport);

  const leagues = useQuery({
    queryKey: ["leagues", active?.sport],
    queryFn: () => api.leagues(active!.sport),
    enabled: Boolean(active),
  });
  const league: League | undefined = (leagues.data ?? []).find((l) => l.league_id === leagueId) ?? leagues.data?.[0];

  // A sport that cannot trade must not leave the tab selected behind it.
  const views: SportView[] = active?.supports_trades ? ["scout", "team", "trade"] : ["scout", "team"];
  const current: SportView = views.find((v) => v === view) ?? "scout";

  return (
    <div className="grid min-h-full grid-cols-[13rem_minmax(0,1fr)]">
      <nav className="flex flex-col gap-6 border-r border-border bg-card px-3 py-4">
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
              key={s.sport}
              active={s.sport === active?.sport}
              disabled={!s.configured}
              title={s.configured ? undefined : `Not configured — set ${s.requires} in .env`}
              onClick={() => {
                setSport(s.sport);
                setLeagueId(null);
                if (view === "home") setView("scout");
              }}
            >
              {s.label.replace(/\s*\(.*\)$/, "")}
              {!s.configured && <span className="font-mono text-[10px] opacity-60">off</span>}
            </RailItem>
          ))}
        </Group>

        {active && (
          <Group label="View">
            {views.map((v) => (
              <RailItem key={v} active={v === current} onClick={() => setView(v)}>
                {{ scout: "Scout", team: "My team", trade: "Trade" }[v]}
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
          {/* Mock mode is invisible once it leaves the sidebar, and a canned
              report reads exactly like a real one — so say so, always. */}
          {mockOn && (
            <Badge variant="warn" appearance="status" className="mx-1" title="Reports are canned; league data is live">
              Mock AI
            </Badge>
          )}

          <div className="flex items-center gap-1">
            <RailItem className="flex-1" active={view === "settings"} onClick={() => setView("settings")}>
              <span className="flex items-center gap-2">
                <Settings className="size-3.5" aria-hidden />
                Settings
              </span>
            </RailItem>
            <Button
              variant="ghost"
              size="icon"
              aria-label={mode === "dark" ? "Switch to light" : "Switch to dark"}
              onClick={() => setMode(mode === "dark" ? "light" : "dark")}
            >
              {mode === "dark" ? <Sun /> : <Moon />}
            </Button>
          </div>
        </div>
      </nav>

      <main className="min-w-0">
        {view === "settings" ? (
          <SettingsPanel />
        ) : sports.isSuccess && configured.length === 0 ? (
          <Empty sports={sports.data} />
        ) : view === "home" ? (
          sports.isSuccess ? (
            <Landing
              sports={sports.data}
              onPick={(picked, picked_league) => {
                setSport(picked.sport);
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
          current === "scout" ? (
            <ScoutPanel sport={active} league={league} />
          ) : current === "team" ? (
            <TeamPanel sport={active} league={league} />
          ) : (
            <TradePanel sport={active} league={league} />
          )
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
  children,
  ...props
}: React.ComponentProps<"button"> & { active?: boolean }) {
  return (
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
}

/** Nothing is configured — say what to set rather than showing an empty shell. */
function Empty({ sports }: { sports: Sport[] }) {
  return (
    <div className="mx-auto max-w-xl p-10">
      <h1 className="font-display text-2xl font-semibold tracking-tight">No sports configured</h1>
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
