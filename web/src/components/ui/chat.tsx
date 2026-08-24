import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { SendHorizontal } from "lucide-react";
import { api } from "@/lib/api";
import { IconButton } from "@/components/ui/icon-button";
import { Card, CardHeader } from "@/components/ui/card";
import { cn } from "@/lib/utils";

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
