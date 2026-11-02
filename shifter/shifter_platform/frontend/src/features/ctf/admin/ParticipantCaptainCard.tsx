import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useCtfEvent } from "@/api/ctfAdmin";
import { apiFetch } from "@/api/client";
import { describeMutationError } from "@/api/errors";
import type { CtfOrganizerParticipantDetail } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

export function ParticipantCaptainCard({ participant }: Readonly<{ participant: CtfOrganizerParticipantDetail }>) {
  const cache = useQueryClient();
  const event = useCtfEvent(participant.event_id, Boolean(participant.team_id));
  const assign = useMutation({
    mutationFn: () => apiFetch(`/api/v1/ctf/teams/${participant.team_id}/captain/`, {
      method: "POST", body: { participant_id: participant.id },
    }),
    onSuccess: () => cache.invalidateQueries({ queryKey: ["ctf"] }),
  });
  const error = describeMutationError(assign.error, "Could not reassign captaincy.");
  const capabilities = event.data?.access_capabilities ?? [];
  const canManage = event.data?.access_source === "owner" || event.data?.access_source === "platform_admin" || capabilities.includes("teams");
  if (!participant.team_id || !canManage) return null;
  const isCaptain = participant.team_captain_id === participant.id;
  return <Card><CardContent>
    <h2 className="mb-2 font-semibold">Team captain</h2>
    <p className="mb-3 text-sm">{isCaptain ? "This participant is the team captain." : "Assign this team member as captain."}</p>
    <Button disabled={isCaptain || assign.isPending} onClick={() => assign.mutate()}>
      {assign.isPending ? "Assigning…" : "Make team captain"}
    </Button>
    {error ? <p role="alert" className="mt-2 text-destructive">{error}</p> : null}
  </CardContent></Card>;
}
