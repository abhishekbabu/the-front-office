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
  configured: boolean;
  requires: string;
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

export type ScoutReport = {
  situation: string;
  focus: string[];
  moves: Move[];
  strategy: string;
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
export type Evaluation = { verdict: TradeVerdict; chat_id: string };
export type RosterRow = Record<string, string>;

/** A failure the server described in its own words, ready to show as-is. */
export class ApiError extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "content-type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    // Every expected failure carries `detail` written for a person; anything
    // without one is a genuine fault and gets the status line instead.
    const body = await response.json().catch(() => null);
    throw new ApiError(body?.detail ?? `${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

const post = <T,>(path: string, body: unknown) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body) });

export const api = {
  sports: () => request<Sport[]>("/api/sports"),
  leagues: (sport: string) => request<League[]>(`/api/${sport}/leagues`),
  roster: (sport: string, league: string) => request<RosterRow[]>(`/api/${sport}/leagues/${league}/roster`),
  scout: (sport: string, league: string, mock: boolean) =>
    post<Analysis>(`/api/${sport}/leagues/${league}/scout`, { mock }),
  trade: (sport: string, league: string, text: string, mock: boolean) =>
    post<Evaluation>(`/api/${sport}/leagues/${league}/trade`, { text, mock }),
  ask: (chatId: string, message: string) => post<{ answer: string }>(`/api/chat/${chatId}`, { message }),
};
