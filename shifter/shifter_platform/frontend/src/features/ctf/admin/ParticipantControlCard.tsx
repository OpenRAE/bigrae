import { useState } from "react";

import { useBootstrap } from "@/api/bootstrap";
import { describeMutationError } from "@/api/errors";
import {
  useActivateControl, useControlCommand, useControlOptions, useControlState, useRetryControlCommand,
  type ControlCommand, type ControlState,
} from "@/api/participant-control";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

import { titleCase } from "../format";

type Reference = ControlState["commands"][number];

export function ParticipantControlCard({ participantId }: Readonly<{ participantId: string }>) {
  const bootstrap = useBootstrap();
  const enabled = bootstrap.data?.participant_control_available === true;
  const options = useControlOptions(participantId, enabled);
  const activate = useActivateControl(participantId);
  const [confirmActivation, setConfirmActivation] = useState(false);
  if (!enabled) return null;
  return <Card><CardContent className="space-y-3">
    <h2 className="text-lg font-semibold">Supervised range power</h2>
    <p>Pause or resume the assigned range after human review. The service checks current permissions,
      review state and resources before each operation.</p>
    {options.isPending ? <output>Loading controls…</output> : null}
    {options.error ? <ControlError error={options.error} /> : null}
    {options.data?.binding_id ? <BoundControls key={options.data.binding_id} binding={options.data.binding_id} /> : <>
      {options.data?.requires_refresh ? <p>The source mapping needs an administrator’s review before activation.</p> : null}
      {options.data && !options.data.configuration_id && !options.data.requires_refresh ?
        <p>No supervised power mapping is configured for this range.</p> : null}
      {options.data?.configuration_id ? <Button onClick={() => setConfirmActivation(true)}>Activate supervised power</Button> : null}
      <ConfirmDialog open={confirmActivation} title="Activate supervised range power?" confirmLabel="Activate"
        pending={activate.isPending} error={activate.error} onOpenChange={setConfirmActivation}
        onConfirm={() => { if (options.data?.configuration_id) activate.mutate(options.data.configuration_id, {
          onSuccess: () => setConfirmActivation(false),
        }); }}>
        Bind the configured human review process to this assigned range. This does not pause or resume it.
      </ConfirmDialog>
    </>}
  </CardContent></Card>;
}

function ControlError({ error }: Readonly<{ error: unknown }>) {
  return <Alert variant="destructive"><AlertDescription>
    {describeMutationError(error, "The control request could not be confirmed.")}
  </AlertDescription></Alert>;
}

function BoundControls({ binding }: Readonly<{ binding: string }>) {
  const [before, setBefore] = useState<string>();
  const latest = useControlState(binding);
  const page = useControlState(binding, before);
  const command = useControlCommand(binding);
  const retry = useRetryControlCommand(binding);
  const [review, setReview] = useState<ControlCommand | null>(null);
  const busy = command.isPending || retry.isPending;
  const state = latest.data;
  function prepare(kind: ControlCommand["kind"], verb: ControlCommand["verb"], reference?: Reference) {
    if (!state) return;
    const request = kind === "proposal" ? crypto.randomUUID() : kind === "action" ? reference!.action_id : crypto.randomUUID();
    setReview({ request_id: request, kind, verb,
      proposal_id: kind === "proposal" ? request : reference!.proposal_id,
      action_id: kind === "proposal" ? crypto.randomUUID() : reference!.action_id,
      expected_cut_digest: state.control_cut_digest,
      decision_id: kind === "cancellation" && reference?.kind === "approval" ? reference.id : null,
    });
    command.reset();
    retry.reset();
  }
  return <>
    {latest.isPending ? <output>Loading control history…</output> : null}
    {latest.error ? <ControlError error={latest.error} /> : null}
    {state ? <>
      <p>Native range status: <strong>{titleCase(state.range_status)}</strong></p>
      <p>Review admission does not confirm a cloud operation or readiness. Recorded requests below may have been
        superseded; the service verifies every new request against the current history.</p>
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" disabled={busy || latest.isFetching} onClick={() => prepare("proposal", "pause")}>Propose pause</Button>
        <Button variant="outline" disabled={busy || latest.isFetching} onClick={() => prepare("proposal", "resume")}>Propose resume</Button>
        <Button variant="ghost" disabled={busy || latest.isFetching} onClick={() => { void latest.refetch(); }}>Refresh status</Button>
      </div>
      {retry.error ? <ControlError error={retry.error} /> : null}
      {retry.data ? <output>Original request admission: {retry.data.state}.</output> : null}
      {page.error ? <ControlError error={page.error} /> : null}
      {page.data ? <>
        <h3 className="font-semibold">Recorded requests</h3>
        {page.data.commands.length === 0 ? <p>No control requests yet.</p> : <ul className="space-y-3">
          {page.data.commands.map((row) => <li key={row.id} className="space-y-1 rounded border p-3">
            <p>{titleCase(row.verb)} · {titleCase(row.kind)} · {row.operation_state ?? "Response unavailable"}</p>
            <p className="break-all text-xs">Request {row.id}</p>
            <div className="flex flex-wrap gap-2" aria-label={`Actions for request ${row.id}`}>
              <Button size="sm" variant="outline" disabled={busy} onClick={() => retry.mutate(row.id)}>Retry original request</Button>
              {row.kind === "proposal" && row.operation_state === "succeeded" ? <>
                <Button size="sm" variant="outline" disabled={busy} onClick={() => prepare("approval", row.verb as ControlCommand["verb"], row)}>Approve {row.verb}</Button>
                <Button size="sm" variant="outline" disabled={busy} onClick={() => prepare("denial", row.verb as ControlCommand["verb"], row)}>Deny {row.verb}</Button>
                <Button size="sm" variant="outline" disabled={busy} onClick={() => prepare("cancellation", row.verb as ControlCommand["verb"], row)}>Cancel proposal</Button>
              </> : null}
              {row.kind === "approval" && row.operation_state === "succeeded" ? <>
                <Button size="sm" disabled={busy} onClick={() => prepare("action", row.verb as ControlCommand["verb"], row)}>Request reviewed {row.verb}</Button>
                <Button size="sm" variant="outline" disabled={busy} onClick={() => prepare("cancellation", row.verb as ControlCommand["verb"], row)}>Cancel approval</Button>
              </> : null}
            </div>
          </li>)}
        </ul>}
        <div className="flex gap-2">
          {before ? <Button variant="outline" onClick={() => setBefore(undefined)}>Latest requests</Button> : null}
          {page.data.next_before ? <Button variant="outline" onClick={() => setBefore(page.data!.next_before!)}>Earlier requests</Button> : null}
        </div>
      </> : null}
    </> : null}
    <ConfirmDialog open={review !== null} title={review ? `${titleCase(review.kind)}: ${review.verb} range?` : "Review request"}
      confirmLabel="Submit original request" pending={busy} error={command.error}
      onOpenChange={(open) => { if (!open) setReview(null); }}
      onConfirm={() => { if (review) command.mutate(review, { onSuccess: () => { setReview(null); setBefore(undefined); } }); }}>
      {review?.kind === "action" ? "This may change every member of the assigned range. " : "This records a human review request. "}
      If the response is lost, resubmit this same request or use its recorded request ID to recover the result.
      The original request and review context are retained.
    </ConfirmDialog>
  </>;
}
