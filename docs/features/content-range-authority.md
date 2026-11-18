# Content, ranges and continuing access

This explanation describes the current principal and policy boundary.
Use [range operations](ranges.md) and [account administration](account-administration.md) for task instructions.

Human and service principals use current application permissions and credential limits.
A service acts as its own identity.
Its creator or contact does not supply permissions.

Content, installers, source credentials, and preparation results belong to an explicit customer scope.
An operator catalog entry does not publish customer credentials or private preparation material.
Account-level ranges need no synthetic organization or workspace.
Service-owned ranges use the tenant lease policy and their actual scope limits.

Revocation blocks further authorized launch, retry, and access operations.
Queued work retains its original credential limits.
Later grants cannot broaden an already accepted operation.
Authorized ownership and scope moves preserve range identity and history.
Required cleanup retains authority for the accepted resource generation.

Remote sessions recheck the original credential and resource permission, including while idle.
Denial or an authority-service outage closes the native transport after a finite interval.
The [technical guide](../technical/shifter_platform/content-range-authority.md) records tested bounds and deployment prerequisites.

An already issued download or upload URL remains usable until its provider expiry.
Revocation prevents new issuance and finalization.
It cannot recall bytes already delivered to a client.
