import { useState } from "react";

import { useBootstrap } from "@/api/bootstrap";
import { describeMutationError } from "@/api/errors";
import { useConfigureControl, useControlConfiguration, type ControlSelection } from "@/api/participant-control";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const FIELDS: ReadonlyArray<{ key: keyof ControlSelection; label: string }> = [
  { key: "participant_address", label: "Participant address" },
  { key: "controller_address", label: "Controller address" },
  { key: "pause_action_contract_address", label: "Pause action address" },
  { key: "resume_action_contract_address", label: "Resume action address" },
  { key: "observation_boundary_address", label: "Observation boundary address" },
];
const EMPTY: ControlSelection = {
  participant_address: "", controller_address: "", pause_action_contract_address: "",
  resume_action_contract_address: "", observation_boundary_address: "",
};

export function PackControlConfiguration({ organization, source, digest }: Readonly<{
  organization: string; source: string; digest: string;
}>) {
  const bootstrap = useBootstrap();
  const enabled = bootstrap.data?.participant_control_available === true;
  const query = useControlConfiguration(organization, source, enabled);
  if (!enabled) return null;
  const error = describeMutationError(query.error, "Control configuration could not be loaded.");
  return <section className="space-y-3 rounded border p-4" aria-label="Supervised range power configuration">
    <h3 className="text-lg font-semibold">Supervised range power</h3>
    <p>Use the logical addresses supplied by the pack author. Each pause or resume requires a recorded human approval.
      This configuration does not start a range or install executable code.</p>
    {query.isPending ? <output>Loading control configuration…</output> : null}
    {error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}
    {query.data ? <ControlMappingForm key={`${source}:${digest}`}
      organization={organization} source={source} digest={digest}
      initial={query.data.configuration?.selection ?? EMPTY} stale={query.data.requires_refresh} /> : null}
  </section>;
}

function ControlMappingForm({ organization, source, digest, initial, stale }: Readonly<{
  organization: string; source: string; digest: string; initial: ControlSelection; stale: boolean;
}>) {
  const [selection, setSelection] = useState(initial);
  const [review, setReview] = useState(false);
  const update = useConfigureControl(organization, source);
  const valid = FIELDS.every(({ key }) => selection[key].trim().length > 0 && selection[key].length <= 256);
  return <>
    {stale ? <p role="status">The pack or control policy changed. Review and save the mapping before new activation.</p> : null}
    <p>Configuration changes are refused while a range uses the current mapping. Existing control history is retained.</p>
    <form className="space-y-3" onSubmit={(event) => { event.preventDefault(); if (valid) setReview(true); }}>
      {FIELDS.map(({ key, label }) => <div key={key}>
        <Label htmlFor={`control-${key}`}>{label}</Label>
        <Input id={`control-${key}`} value={selection[key]} maxLength={256} required disabled={update.isPending}
          onChange={(event) => { setSelection({ ...selection, [key]: event.target.value }); update.reset(); }} />
      </div>)}
      <Button type="submit" disabled={!valid || update.isPending}>Review control configuration</Button>
    </form>
    {update.isSuccess ? <output className="block">Control mapping saved. An organizer can activate it for a qualified range.</output> : null}
    <ConfirmDialog open={review} title="Save this control mapping?" confirmLabel="Save mapping"
      pending={update.isPending} error={update.error} onOpenChange={setReview} confirmDisabled={!valid}
      onConfirm={() => update.mutate({ expected_package_digest: digest, selection }, { onSuccess: () => setReview(false) })}>
      BigRAE will verify these addresses against the exact pack version. Range activation and every power operation
      still require their own permissions and resource checks.
    </ConfirmDialog>
  </>;
}
