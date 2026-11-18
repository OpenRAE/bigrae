# Range-to-workspace scoping administration

Move an eligible range's workspace scope without changing its owner or lifecycle.
Use **Range scoping** inside the selected workspace under **Administer > Accounts**.

## Access

You need current scope-management authority for both source and destination.
The native credential must permit those actions too.
A staff flag, membership, or owner label alone does not authorize a move.
The [technical reference](../technical/shifter_platform/range-workspace-scoping-administration.md) defines the exact checks.

## Viewing ranges scoped to a workspace

1. Open the permitted workspace.
2. Read **Range scoping**.
3. Use **Previous ranges** or **Next ranges** to inspect another page.

Rows show the scenario, status, and owner reference.
Administrative visibility does not grant a terminal session or access to range secrets.

## Reassigning a range to another workspace

Confirm that the owner is an active member of the destination.
The destination must be active and have sufficient applicable quota.

1. Select **Move** for the eligible range.
2. Enter **Destination workspace UUID**.
3. Check the range and destination.
4. Select **Confirm range move**.
5. Read the result before retrying.

The owning service moves persisted ancestry and the active reservation together.
The range retains its identity, owner, lifecycle, lease, and history.
A same-workspace move makes no change.

## What you cannot reassign here

An event-owned aggregate cannot be moved independently from its event.
A conflicting move or inconsistent projection is refused.
Ask the operator to resolve the condition before retrying.

## What this surface does not do

Use [range operations](ranges.md) for launch, pause, resume, extension, and destruction.
Use [workspace membership](workspaces.md) for members and invitations.
A scope move alone does not share a range with every destination member.
