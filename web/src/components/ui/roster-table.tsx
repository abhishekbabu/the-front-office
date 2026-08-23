import { DataTable } from "@/components/ui/data-table";
import { Badge } from "@/components/ui/badge";
import { Empty } from "@/components/ui/state";
import type { PlayerCard } from "@/lib/api";

/** Columns whose values are figures, so they align right like numbers. */
const NUMERIC = new Set([
  "xPts",
  "Price",
  "Proj",
  "Points",
  "Form",
  "xGI",
  "Owned",
  "Depth",
  "Exp",
  "PTS",
  "REB",
  "AST",
]);

/**
 * Values that mean "look at this".
 *
 * The provider writes a status in the platform's own words — "doubtful 75%",
 * "Questionable", "OUT" — so anything non-empty is worth a badge, and the two
 * that mean definitely-not-playing get the stronger one.
 */
function statusTone(value: string): "fail" | "warn" {
  return /\b(out|suspended|injured|ir)\b/i.test(value) ? "fail" : "warn";
}

/**
 * A list of players, however it was arrived at.
 *
 * Your squad, somebody else's, and the wire are the same table with different
 * rows — each provider returns the same columns for all three, so the one that
 * knows how to render them is shared rather than written out per panel.
 */
export function RosterTable({
  players,
  empty,
  onOpen,
}: {
  players: PlayerCard[];
  empty: { title: string; detail?: string };
  onOpen?: (playerId: string) => void;
}) {
  if (players.length === 0) return <Empty title={empty.title} detail={empty.detail} />;
  return (
    <DataTable
      rows={players}
      numeric={NUMERIC}
      onSelect={onOpen && ((row) => onOpen(row.player_id))}
      render={(column, value) =>
        column === "Status" && value ? (
          <Badge variant={statusTone(value)} appearance="status">
            {value}
          </Badge>
        ) : column === "Player" ? (
          <span className="font-medium">{value}</span>
        ) : column === "Slot" ? (
          <span className="font-mono text-[11px] text-muted-foreground">{value}</span>
        ) : undefined
      }
    />
  );
}
