import { useQuery } from "@tanstack/react-query";
import { api, type League, type RosterRow, type Sport } from "@/lib/api";
import { Card, CardHeader } from "@/components/ui/card";
import { Table, Td, Th, Tr } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorNote, PageHeader } from "@/panels/shared";
import { cn } from "@/lib/utils";

/** Columns whose values are figures, so they align right like the numbers they are. */
const NUMERIC = new Set(["xPts", "Price", "Proj", "Points"]);

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

export function TeamPanel({ sport, league }: { sport: Sport; league: League }) {
  const roster = useQuery<RosterRow[], Error>({
    queryKey: ["roster", sport.sport, league.league_id],
    queryFn: () => api.roster(sport.sport, league.league_id),
  });

  // The columns are the sport's own vocabulary — FPL sends Price and xPts, NFL
  // sends Slot — so they are read off the data rather than declared per sport.
  const columns = roster.data?.[0] ? Object.keys(roster.data[0]) : [];

  return (
    <>
      <PageHeader title={league.name} meta={league.detail} />

      {roster.isError && <ErrorNote error={roster.error} />}

      <div className="p-5">
        <Card>
          <CardHeader>
            <span>{sport.label.replace(/\s*\(.*\)$/, "")} squad</span>
            {roster.data && <span>{roster.data.length} players</span>}
          </CardHeader>

          {roster.isLoading && <Skeleton className="m-4 h-64" />}

          {roster.data && (
            <Table>
              <thead>
                <tr>
                  {columns.map((column) => (
                    <Th key={column} className={cn(NUMERIC.has(column) && "text-right")}>
                      {column}
                    </Th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {roster.data.map((row, i) => (
                  <Tr key={i}>
                    {columns.map((column) => {
                      const value = row[column] ?? "";
                      return (
                        <Td key={column} className={cn(NUMERIC.has(column) && "text-right")}>
                          {column === "Status" && value ? (
                            <Badge variant={statusTone(value)} appearance="status">
                              {value}
                            </Badge>
                          ) : column === "Player" ? (
                            <span className="font-medium">{value}</span>
                          ) : column === "Slot" ? (
                            <span className="font-mono text-[11px] text-muted-foreground">{value}</span>
                          ) : (
                            value
                          )}
                        </Td>
                      );
                    })}
                  </Tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card>
      </div>
    </>
  );
}
