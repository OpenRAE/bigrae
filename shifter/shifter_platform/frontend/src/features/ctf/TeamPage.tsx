import { useState } from "react";

import {
  useCreateTeam,
  useCtfTeam,
  useDisbandTeam,
  useJoinTeam,
  useLeaveTeam,
  useRegenerateTeamCode,
  useRemoveTeamMember,
  useRenameTeam,
  useTransferCaptaincy,
} from "@/api/ctf";
import { describeMutationError } from "@/api/errors";
import type { CtfTeam, CtfTeamRegenerateCodeRequest } from "@/api/types";
import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";

function MutationError({ error }: Readonly<{ error: unknown }>) {
  const message = describeMutationError(error, "That did not work. Try again.");
  if (!message) return null;
  return <p className="mt-2 text-xs text-destructive">{message}</p>;
}

/** Create-or-join forms shown when the participant has no team. */
function NoTeamActions() {
  const create = useCreateTeam();
  const join = useJoinTeam();
  const [name, setName] = useState("");
  const [code, setCode] = useState("");

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <Card>
        <CardContent>
          <h2 className="text-sm font-semibold">Create a team</h2>
          <form
            className="mt-3 flex flex-col gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              if (name.trim()) create.mutate({ name: name.trim() });
            }}
          >
            <Label htmlFor="team-name">Team name</Label>
            <Input id="team-name" value={name} onChange={(event) => setName(event.target.value)} />
            <Button type="submit" disabled={!name.trim() || create.isPending}>
              Create team
            </Button>
          </form>
          <MutationError error={create.error} />
        </CardContent>
      </Card>
      <Card>
        <CardContent>
          <h2 className="text-sm font-semibold">Join a team</h2>
          <form
            className="mt-3 flex flex-col gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              if (code.trim()) join.mutate({ invite_code: code.trim() });
            }}
          >
            <Label htmlFor="team-code">Invite code</Label>
            <Input id="team-code" value={code} onChange={(event) => setCode(event.target.value)} />
            <Button type="submit" disabled={!code.trim() || join.isPending}>
              Join team
            </Button>
          </form>
          <MutationError error={join.error} />
        </CardContent>
      </Card>
    </div>
  );
}

const SELECT_CLASS = "h-9 rounded-md border border-input bg-background px-2 text-sm";

/** Invite code display, settings, and regenerate, shown to the captain only. */
function CaptainInviteCode({ team }: Readonly<{ team: CtfTeam }>) {
  const regenerate = useRegenerateTeamCode();
  // "" means keep the current server value; the request omits unedited settings
  // so a routine rotation never drops a restriction (CTF-504).
  const [mode, setMode] = useState("");
  const [expiry, setExpiry] = useState("");
  // Show regeneration to the captain even when the code is null, so an expired
  // or spent code can be replaced.
  if (!team.is_captain) return null;

  const onRegenerate = () => {
    const body: CtfTeamRegenerateCodeRequest = {};
    if (mode === "single") body.single_use = true;
    else if (mode === "multi") body.single_use = false;
    if (expiry === "none") body.expires_in_seconds = null;
    else if (expiry !== "") body.expires_in_seconds = Number(expiry);
    regenerate.mutate(body);
  };

  return (
    <Card>
      <CardContent>
        <h2 className="text-sm font-semibold">Invite code</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          Share this code so teammates can join. Regenerating invalidates the old code.
        </p>
        <div className="mt-2 flex items-center gap-2">
          {team.invite_code ? (
            <code className="rounded bg-muted px-2 py-1 font-mono text-sm">{team.invite_code}</code>
          ) : (
            <span className="text-sm text-muted-foreground">No active code. Regenerate to create one.</span>
          )}
        </div>
        <p className="mt-1 text-xs text-muted-foreground">
          {team.invite_code_single_use ? "Single-use" : "Multi-use"}
          {" · "}
          {team.invite_code_expires_at
            ? `expires ${new Date(team.invite_code_expires_at).toLocaleString()}`
            : "no expiry"}
        </p>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <div className="flex flex-col gap-1">
            <Label htmlFor="invite-mode">Use mode</Label>
            <select
              id="invite-mode"
              className={SELECT_CLASS}
              value={mode}
              onChange={(event) => setMode(event.target.value)}
            >
              <option value="">Keep current</option>
              <option value="multi">Multi-use</option>
              <option value="single">Single-use</option>
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="invite-expiry">Expiry</Label>
            <select
              id="invite-expiry"
              className={SELECT_CLASS}
              value={expiry}
              onChange={(event) => setExpiry(event.target.value)}
            >
              <option value="">Keep current</option>
              <option value="none">No expiry</option>
              <option value="3600">1 hour</option>
              <option value="21600">6 hours</option>
              <option value="86400">24 hours</option>
              <option value="604800">7 days</option>
            </select>
          </div>
        </div>
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="mt-3"
          disabled={regenerate.isPending}
          onClick={onRegenerate}
        >
          Regenerate
        </Button>
        <MutationError error={regenerate.error} />
      </CardContent>
    </Card>
  );
}

/** Captain-only rename control. */
function CaptainRename({ team }: Readonly<{ team: CtfTeam }>) {
  const rename = useRenameTeam();
  const [name, setName] = useState(team.name);
  return (
    <form
      className="flex flex-wrap items-end gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        if (name.trim() && name.trim() !== team.name) rename.mutate({ name: name.trim() });
      }}
    >
      <div className="flex min-w-56 flex-1 flex-col gap-1">
        <Label htmlFor="team-rename">Team name</Label>
        <Input id="team-rename" value={name} onChange={(event) => setName(event.target.value)} />
      </div>
      <Button type="submit" variant="outline" disabled={rename.isPending || !name.trim() || name.trim() === team.name}>
        Rename
      </Button>
      <MutationError error={rename.error} />
    </form>
  );
}

function MemberRow({ team, member }: Readonly<{ team: CtfTeam; member: CtfTeam["members"][number] }>) {
  const transfer = useTransferCaptaincy();
  const remove = useRemoveTeamMember();
  return (
    <li className="py-2 text-sm">
      <div className="flex items-center justify-between gap-3">
        <span className="flex items-center gap-2">
          {member.name}
          {member.is_captain ? <Badge variant="secondary">Captain</Badge> : null}
        </span>
        {team.is_captain && !member.is_captain ? (
          <span className="flex gap-1.5">
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={transfer.isPending}
              onClick={() => transfer.mutate({ participant_id: member.id })}
            >
              Make captain
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={remove.isPending}
              onClick={() => remove.mutate({ participant_id: member.id })}
            >
              Remove
            </Button>
          </span>
        ) : null}
      </div>
      <MutationError error={transfer.error ?? remove.error} />
    </li>
  );
}

/** Leave (member) or disband (captain) control at the foot of the page. */
function DangerActions({ team }: Readonly<{ team: CtfTeam }>) {
  const leave = useLeaveTeam();
  const disband = useDisbandTeam();

  return (
    <div className="flex flex-col items-start gap-1">
      {team.is_captain && team.members.length > 1 ? (
        <p className="text-xs text-muted-foreground">
          Transfer captaincy before leaving, or disband the team below.
        </p>
      ) : null}
      <div className="flex gap-2">
        {team.is_captain ? (
          <Button type="button" variant="destructive" disabled={disband.isPending} onClick={() => disband.mutate({})}>
            Disband team
          </Button>
        ) : (
          <Button type="button" variant="outline" disabled={leave.isPending} onClick={() => leave.mutate({})}>
            Leave team
          </Button>
        )}
      </div>
      <MutationError error={disband.error ?? leave.error} />
    </div>
  );
}

function TeamDetail({ team }: Readonly<{ team: CtfTeam }>) {
  const count = team.members.length;
  const memberNoun = count === 1 ? "member" : "members";
  const limitSuffix = team.team_size_limit ? ` · limit ${team.team_size_limit}` : "";
  return (
    <>
      <PageHeader
        title={team.name}
        description={`${count} ${memberNoun}${limitSuffix}`}
      />
      <div className="space-y-4">
        {team.is_captain ? (
          <Card>
            <CardContent className="space-y-4">
              <CaptainRename team={team} />
            </CardContent>
          </Card>
        ) : null}
        <CaptainInviteCode team={team} />
        <Card>
          <CardContent>
            <h2 className="text-sm font-semibold">Members</h2>
            <ul className="mt-2 divide-y divide-border/60">
              {team.members.map((member) => (
                <MemberRow key={member.id} team={team} member={member} />
              ))}
            </ul>
          </CardContent>
        </Card>
        <DangerActions team={team} />
      </div>
    </>
  );
}

export function TeamPage() {
  const query = useCtfTeam();

  if (query.isLoading) {
    return (
      <>
        <PageHeader title="Team" />
        <Skeleton className="h-40 w-full" />
      </>
    );
  }

  // The hook resolves the server's 404 "not on a team" answer to null.
  if (query.data === null) {
    return (
      <>
        <PageHeader title="Team" description="Create a team or join one with an invite code" />
        <NoTeamActions />
      </>
    );
  }

  if (query.isError || !query.data) {
    return (
      <>
        <PageHeader title="Team" />
        <Alert variant="destructive">
          <AlertTitle>Could not load your team</AlertTitle>
          <AlertDescription>Please retry.</AlertDescription>
        </Alert>
      </>
    );
  }

  return <TeamDetail team={query.data} />;
}
