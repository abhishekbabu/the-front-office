/**
 * The API client.
 *
 * Types here mirror the response models in `adapters/inbound/web/api.py`, which
 * are the domain models themselves — so a field added to `ScoutReport` shows up
 * as a typecheck failure here rather than as an undefined at runtime.
 */

export type Sport = {
  sport: string;
  label: string;
  supports_trades: boolean;
  /** Whether the credentials this sport needs are set. */
  configured: boolean;
  requires: string;
  /** Whether it can actually be used. Configured is necessary, not sufficient. */
  ready: boolean;
  /** What stands in the way, and which remedy to offer. Empty when ready. */
  blocked_reason: string;
  blocked_code: string;
};

export type League = { league_id: string; name: string; detail: string };

export type MoveAction = "ADD" | "DROP" | "START" | "BENCH" | "TRANSFER" | "CAPTAIN" | "MONITOR";

export type Move = {
  action: MoveAction;
  player: string;
  position: string;
  team: string;
  metric: string;
  rationale: string;
  replaces: string;
  replaces_rationale: string;
};

export type Tone = "neutral" | "good" | "warning";

export type Stat = { label: string; value: string; tone: Tone };

/** One place in a lineup, or one player on a bench. */
export type Spot = {
  player_id: string;
  slot: string;
  player: string;
  detail: string;
  value: string;
  tone: Tone;
};

/** A change the numbers already imply, before anyone has judged them. */
export type Swap = { start: string; out: string; gain: string };

/** One team in a matchup — yours, or the one you are playing. */
export type Side = { name: string; detail: string; points: string; lineup: Spot[]; bench: Spot[] };

export type Summary = {
  headline: Stat[];
  mine: Side | null;
  /** Null when the week has no fixture, which is not a nil-nil scoreline. */
  opponent: Side | null;
  swaps: Swap[];
  fixtures: Stat[];
};

export type ScoutReport = {
  situation: string;
  focus: string[];
  moves: Move[];
  strategy: string;
  /** Read off the platform by the provider, not written by the model. */
  headline: Stat[];
};

export type TradeVerdict = {
  verdict: "ACCEPT" | "REJECT" | "COUNTER";
  verdict_detail: string;
  gains: string[];
  losses: string[];
  impact: string;
  schedule: string;
  risk: string;
  strategy: string;
};

export type Analysis = { report: ScoutReport; chat_id: string };

/** What this installation can do, as opposed to what it knows how to do. */
export type Capabilities = { ai: boolean };

export type Setting = {
  key: string;
  field: string;
  secret: boolean;
  /** Whether a value is set. For a secret this is all the client is ever told. */
  present: boolean;
  /** Always empty for a secret; a secret's characters never leave the server. */
  value: string;
  /** A shell variable is overriding .env, so an edit here will not take effect. */
  shadowed: boolean;
  /** Which control to render: text, boolean, integer, number or choice. */
  kind: "text" | "boolean" | "integer" | "number" | "choice";
  choices: string[];
};
export type Evaluation = { verdict: TradeVerdict; chat_id: string };
/** A player as a table row: the sport's own columns, plus what a column cannot be. */
export type PlayerCard = { player_id: string; columns: Record<string, string>; tone: Tone };

export type PlayerDetail = {
  player_id: string;
  name: string;
  position: string;
  team: string;
  headline: string;
  note: string;
  tone: Tone;
  stats: Stat[];
};

/**
 * A failure the server described in its own words, ready to show as-is.
 *
 * `code` names conditions this app can offer to fix. Matching on it rather than
 * on the message leaves the wording free to change.
 */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly code: string = "error",
  ) {
    super(message);
  }
}

export type LoginState = { status: "idle" | "running" | "ok" | "failed"; detail: string };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "content-type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    // Every expected failure carries `detail` written for a person; anything
    // without one is a genuine fault and gets the status line instead.
    const body = await response.json().catch(() => null);
    throw new ApiError(body?.detail ?? `${response.status} ${response.statusText}`, body?.code);
  }
  return response.json() as Promise<T>;
}

const post = <T,>(path: string, body: unknown) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body) });

const put = <T,>(path: string, body: unknown) =>
  request<T>(path, { method: "PUT", body: JSON.stringify(body) });

export const api = {
  sports: () => request<Sport[]>("/api/sports"),
  leagues: (sport: string) => request<League[]>(`/api/${sport}/leagues`),
  roster: (sport: string, league: string) => request<PlayerCard[]>(`/api/${sport}/leagues/${league}/roster`),
  player: (sport: string, league: string, id: string) =>
    request<PlayerDetail>(`/api/${sport}/leagues/${league}/players/${id}`),
  summary: (sport: string, league: string) => request<Summary>(`/api/${sport}/leagues/${league}/summary`),
  scout: (sport: string, league: string) => post<Analysis>(`/api/${sport}/leagues/${league}/scout`, {}),
  trade: (sport: string, league: string, text: string) =>
    post<Evaluation>(`/api/${sport}/leagues/${league}/trade`, { text }),
  ask: (chatId: string, message: string) => post<{ answer: string }>(`/api/chat/${chatId}`, { message }),
  capabilities: () => request<Capabilities>("/api/capabilities"),
  settings: () => request<Setting[]>("/api/settings"),
  yahooLogin: () => post<LoginState>("/api/yahoo/login", {}),
  yahooLoginState: () => request<LoginState>("/api/yahoo/login"),
  saveSettings: (values: Record<string, string>) => put<Setting[]>("/api/settings", { values }),
};
