import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, SendHorizontal } from "lucide-react";
import { IconButton } from "@/components/ui/icon-button";
import { ApiError, api, type Move } from "@/lib/api";
import { moveTone } from "@/lib/tone";
import { splitMetric } from "@/lib/metric";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/**
 * The bar that says where you are and what you can do from here.
 *
 * Pinned, because both halves stay relevant the whole way down a page: on a
 * long one the title is what a figure belongs to, and the controls are the way
 * out. Opaque rather than translucent — content scrolling visibly underneath
 * a title reads as two pages at once.
 *
 * `leading` sits before the title, which is where a control that leaves the
 * page belongs: back is upstream of where you are, and reads that way to the
 * left of the name of it.
 */
export function PageHeader({
  title,
  meta,
  leading,
  children,
}: {
  title: string;
  meta?: string;
  leading?: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <div className="sticky top-0 z-20 flex flex-wrap items-center justify-between gap-3 border-b border-border bg-background px-5 py-4">
      <div className="flex min-w-0 items-center gap-3">
        {leading}
        <div className="min-w-0">
          <h1 className="font-display text-[21px] font-semibold leading-tight tracking-tight">{title}</h1>
          {meta && <p className="mt-0.5 font-mono text-[12px] text-muted-foreground">{meta}</p>}
        </div>
      </div>
      {children}
    </div>
  );
}

/**
 * One recommendation.
 *
 * Three columns rather than a stack: the action reads as a chip on the left,
 * the reasoning takes the middle at prose width, and the number is right-aligned
 * so the figures form a column you scan down instead of hunting for.
 */
export function MoveRow({ move }: { move: Move }) {
  return (
    <div className="grid grid-cols-[5.5rem_minmax(0,1fr)_auto] items-start gap-4 border-t border-border px-4 py-3.5">
      <Badge variant={moveTone(move.action)} appearance="pill">
        {move.action}
      </Badge>

      <div className="min-w-0">
        <div className="font-display text-base font-semibold leading-snug tracking-tight">{move.player}</div>
        <div className="mt-0.5 font-mono text-[11px] text-muted-foreground">
          {[move.position, move.team].filter(Boolean).join(" · ")}
        </div>
        <p className="mt-1.5 max-w-[54ch] text-[13.5px] leading-relaxed text-muted-foreground">{move.rationale}</p>
        {move.replaces && (
          <div className="mt-2 rounded-md bg-muted px-2.5 py-1.5 text-[12.5px] text-muted-foreground">
            <b className="font-semibold text-foreground">{move.replaces}</b>
            {move.replaces_rationale && ` · ${move.replaces_rationale}`}
          </div>
        )}
      </div>

      <MetricValue metric={move.metric} />
    </div>
  );
}

function MetricValue({ metric }: { metric: string }) {
  const parsed = splitMetric(metric);
  if (parsed.figure === null) {
    return <div className="max-w-[9rem] text-right font-mono text-[11px] text-muted-foreground">{parsed.text}</div>;
  }
  return (
    <div className="text-right">
      <div className="font-display text-[19px] font-semibold tracking-tight tabular-nums text-ok">{parsed.figure}</div>
      {parsed.unit && (
        // Written by the model and often a phrase rather than a unit —
        // "proj pts, +4.1 over Smith". Uppercasing and letter-spacing that
        // makes a long one harder to read, not more label-like.
        <div className="mt-0.5 max-w-[11rem] font-mono text-[10px] leading-snug text-muted-foreground">
          {parsed.unit}
        </div>
      )}
    </div>
  );
}

export function Chips({ items, className }: { items: string[]; className?: string }) {
  if (!items.length) return null;
  return (
    <div className={cn("flex flex-wrap gap-1.5", className)}>
      {items.map((item) => (
        <Badge key={item} variant="muted" appearance="label">
          {item}
        </Badge>
      ))}
    </div>
  );
}

/**
 * A failure, and the one thing this app can do about it.
 *
 * The server describes the condition and deliberately names no command — the
 * same text is read in a terminal — so the remedy is chosen here, off the code.
 */
export function ErrorNote({ error }: { error: unknown }) {
  const code = error instanceof ApiError ? error.code : "error";
  return (
    <div className="m-5 flex flex-col items-start gap-3 rounded-md border border-destructive/30 bg-destructive/8 px-4 py-3">
      <p className="max-w-[70ch] text-[13.5px] leading-relaxed text-destructive">
        {error instanceof Error ? error.message : "Something went wrong."}
      </p>
      {code === "yahoo_login_required" && <YahooLoginButton />}
      {(code === "ai_key_invalid" || code === "ai_unavailable") && (
        <button
          onClick={() => window.dispatchEvent(new CustomEvent("tfo:settings"))}
          className="inline-flex h-9 items-center rounded-md border border-border bg-background px-4 text-sm font-medium hover:bg-muted"
        >
          Open Settings
        </button>
      )}
      {code === "yahoo_not_approved" && (
        <a
          href="https://sports.yahoo.com/developer/access/"
          target="_blank"
          rel="noreferrer"
          className="inline-flex h-9 items-center gap-2 rounded-md border border-border bg-background px-4 text-sm font-medium hover:bg-muted"
        >
          Apply for API access
          <ExternalLink className="size-3.5" aria-hidden />
        </a>
      )}
    </div>
  );
}

/**
 * Starts the Yahoo handshake and watches it.
 *
 * The click cannot be answered by one request: authorizing means a browser tab
 * and a person, so the server starts the flow and reports progress separately.
 */
export function YahooLoginButton() {
  const queryClient = useQueryClient();
  const [watching, setWatching] = useState(false);

  const start = useMutation({ mutationFn: api.yahooLogin, onSuccess: () => setWatching(true) });

  const state = useQuery({
    queryKey: ["yahoo-login"],
    queryFn: api.yahooLoginState,
    enabled: watching,
    refetchInterval: (query) => (query.state.data?.status === "running" ? 1500 : false),
  });

  useEffect(() => {
    if (state.data?.status !== "ok") return;
    setWatching(false);
    // Everything about this sport failed on the missing authorization; none of
    // those answers are worth keeping now that it exists.
    queryClient.invalidateQueries();
  }, [state.data?.status, queryClient]);

  const status = state.data?.status;
  const running = start.isPending || status === "running";

  return (
    <div className="flex flex-col gap-2">
      <Button variant="primary" onClick={() => start.mutate()} disabled={running}>
        {running ? "Waiting for the browser…" : "Authorize Yahoo"}
      </Button>
      {running && (
        <p className="max-w-[60ch] text-[12.5px] text-muted-foreground">
          A tab has opened. Accept the certificate warning if one appears, then approve the app.
        </p>
      )}
      {status === "failed" && (
        <p className="max-w-[70ch] text-[12.5px] leading-relaxed text-destructive">{state.data?.detail}</p>
      )}
    </div>
  );
}

/** Follow-up conversation about a report that is already on screen. */
export function Chat({ chatId }: { chatId: string }) {
  const [turns, setTurns] = useState<{ role: "you" | "model"; text: string }[]>([]);
  const [draft, setDraft] = useState("");

  const ask = useMutation({
    mutationFn: (message: string) => api.ask(chatId, message),
    onSuccess: (reply) => setTurns((t) => [...t, { role: "model", text: reply.answer }]),
    onError: (e: Error) => setTurns((t) => [...t, { role: "model", text: e.message }]),
  });

  function send(e: React.FormEvent) {
    e.preventDefault();
    const message = draft.trim();
    if (!message || ask.isPending) return;
    setTurns((t) => [...t, { role: "you", text: message }]);
    setDraft("");
    ask.mutate(message);
  }

  return (
    <Card>
      <CardHeader>
        <span>Ask a follow-up</span>
        {ask.isPending && <span className="normal-case tracking-normal">Thinking…</span>}
      </CardHeader>
      <div className="flex flex-col gap-3 p-4">
        {turns.map((turn, i) => (
          <div key={i} className={cn("max-w-[62ch] text-[13.5px] leading-relaxed", turn.role === "you" && "self-end")}>
            <div className="mb-0.5 font-mono text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
              {turn.role}
            </div>
            <div className={cn(turn.role === "you" ? "rounded-md bg-muted px-3 py-2" : "text-foreground")}>
              {turn.text}
            </div>
          </div>
        ))}
        <form onSubmit={send} className="flex gap-2">
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Why that move?"
            className="h-9 min-w-0 flex-1 rounded-md border border-input bg-background px-3 text-[13.5px] placeholder:text-muted-foreground"
          />
          <IconButton
            label="Ask"
            side="left"
            variant="primary"
            type="submit"
            icon={<SendHorizontal />}
            disabled={!draft.trim() || ask.isPending}
          />
        </form>
      </div>
    </Card>
  );
}
