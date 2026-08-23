import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Moon, Sun } from "lucide-react";
import { api, type League, type Sport } from "@/lib/api";
import { useTheme } from "@/lib/useTheme";
import { PALETTES } from "@/themes/registry";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { ScoutPanel } from "@/panels/Scout";
import { TeamPanel } from "@/panels/Team";
import { TradePanel } from "@/panels/Trade";
import { cn } from "@/lib/utils";

type View = "scout" | "team" | "trade";

export default function App() {
  const { mode, setMode, palette, setPalette } = useTheme();
  const [sport, setSport] = useState<string | null>(null);
  const [view, setView] = useState<View>("scout");
  const [leagueId, setLeagueId] = useState<string | null>(null);
  const [mock, setMock] = useState(false);

  const sports = useQuery({ queryKey: ["sports"], queryFn: api.sports });
  const configured = useMemo(() => (sports.data ?? []).filter((s) => s.configured), [sports.data]);
  const active: Sport | undefined = configured.find((s) => s.sport === sport) ?? configured[0];

  const leagues = useQuery({
    queryKey: ["leagues", active?.sport],
    queryFn: () => api.leagues(active!.sport),
    enabled: Boolean(active),
  });
  const league: League | undefined = (leagues.data ?? []).find((l) => l.league_id === leagueId) ?? leagues.data?.[0];

  // A sport that cannot trade must not leave the tab selected behind it.
  const views: View[] = active?.supports_trades ? ["scout", "team", "trade"] : ["scout", "team"];
  const current = views.includes(view) ? view : "scout";

  return (
    <div className="grid min-h-full grid-cols-[13rem_minmax(0,1fr)]">
      <nav className="flex flex-col gap-6 border-r border-border bg-card px-3 py-4">
        <div className="flex items-center gap-2.5 px-1">
          <span className="flex size-6 shrink-0 items-center justify-center rounded-sm bg-primary font-display text-[13px] font-bold text-primary-foreground">
            FO
          </span>
          <span className="font-display text-[15px] font-semibold tracking-tight">The Front Office</span>
        </div>

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

        <div className="mt-auto flex flex-col gap-3">
          <label className="flex cursor-pointer items-center justify-between gap-2 px-2 text-[13px] text-muted-foreground">
            <span>Mock AI</span>
            <input
              type="checkbox"
              checked={mock}
              onChange={(e) => setMock(e.target.checked)}
              className="size-3.5 accent-[var(--color-primary)]"
            />
          </label>

          <div className="flex items-center gap-1 px-1">
            {PALETTES.map((p) => (
              <button
                key={p.id}
                onClick={() => setPalette(p.id)}
                title={`${p.label} — ${p.hint}`}
                aria-label={p.label}
                aria-pressed={p.id === palette}
                className={cn(
                  "size-4 rounded-full border transition-transform",
                  p.id === palette ? "scale-110 border-foreground" : "border-border hover:scale-110",
                )}
                style={{ background: p.swatch }}
              />
            ))}
            <Button
              variant="ghost"
              size="icon"
              className="ml-auto"
              aria-label={mode === "dark" ? "Switch to light" : "Switch to dark"}
              onClick={() => setMode(mode === "dark" ? "light" : "dark")}
            >
              {mode === "dark" ? <Sun /> : <Moon />}
            </Button>
          </div>
        </div>
      </nav>

      <main className="min-w-0">
        {sports.isSuccess && configured.length === 0 ? (
          <Empty sports={sports.data} />
        ) : active && league ? (
          current === "scout" ? (
            <ScoutPanel sport={active} league={league} mock={mock} />
          ) : current === "team" ? (
            <TeamPanel sport={active} league={league} />
          ) : (
            <TradePanel sport={active} league={league} mock={mock} />
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
        Set one of these in <code className="font-mono text-accent-foreground">.env</code>, then run{" "}
        <code className="font-mono text-accent-foreground">just doctor</code> to check it took.
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
