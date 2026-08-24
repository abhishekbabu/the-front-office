import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type League, type PlayerCard, type Competition } from "@/lib/api";
import { Card, CardHeader } from "@/components/ui/card";
import { RosterTable } from "@/components/ui/roster-table";
import { Loading } from "@/components/ui/state";
import { PlayerPanel } from "@/components/ui/player";
import { ErrorNote, PageHeader } from "@/panels/shared";

/**
 * The whole squad, in more depth than the week view.
 *
 * This is where you look at your players rather than at this week: the season
 * numbers, the ownership, the depth chart. Any row opens.
 */
export function TeamPanel({ competition, league }: { competition: Competition; league: League }) {
  const [open, setOpen] = useState<string | null>(null);

  const roster = useQuery<PlayerCard[], Error>({
    queryKey: ["roster", competition.key, league.league_id],
    queryFn: () => api.roster(competition.key, league.league_id),
  });

  return (
    <>
      <PageHeader
        title={league.name}
        meta={league.detail}
        href={league.url}
        hrefLabel={`Open ${league.name} on the platform`} />

      {roster.isError && <ErrorNote error={roster.error} />}
      {roster.isLoading && <Loading lines={5} />}

      {roster.data && (
        <div className="p-5">
          <Card>
            <CardHeader>
              <span>Squad</span>
              <span>{roster.data.length} players</span>
            </CardHeader>

            <RosterTable
              players={roster.data}
              empty={{ title: "No players yet", detail: "This roster is empty for the current season." }}
              onOpen={setOpen}
            />
          </Card>
        </div>
      )}

      <PlayerPanel
        competition={competition.key}
        league={league.league_id}
        playerId={open}
        onClose={() => setOpen(null)}
      />
    </>
  );
}
