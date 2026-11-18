# Temporary participant range access

Issue #2785 corrects normal terminal and Guacamole admission for temporary
participants. It adds no credential, role, policy exception or transport.

The temporary credential keeps its existing event-bound ceiling:
`event.read` and `event.participate`. It cannot request `range.access` against
a range leaf. Remote access must use the existing event participation decision
for that participant's own assigned range.

CMS and Engine resolve range, request, owner, parent and account scope from
their own records. A shared request builder checks the following invariants.

| Caller | Required decision and checks |
| --- | --- |
| Temporary participant | The actual parent is the credential's event. The range owner is the caller. CTF confirms live participation and the exact request assignment. Authorize `event.participate` on that event. |
| Other caller | Keep the existing `range.access` decision against the range leaf. Event-owned participant access retains its live assignment check. |
| Other range action | Keep its existing action, target and credential ceiling. |

The shared builder uses the existing registered CTF participation callback.
Engine imports no CTF or CMS implementation. Both owning services apply the
same request rule before secrets or transport. CMS selects the event-management
override or the shared range request in one typed helper. Missing request or owner
facts cause an explicit denial; authorization does not depend on assertions. Guacamole's HTTP admission
accepts event participation for range access. Device access keeps its existing
action ceiling.

The reviewed HTTP surface inventory records both range access and event
participation for these remote endpoints. Range connection requests select
authority from the actual credential kind and event parent. Bootstrap status
and open requests keep their persisted protocol and target selector.

The retained remote binding still names the exact native range, guest, owner,
request, generation and ancestry. Delayed work and open sessions reauthorize
the original session and this same binding. Declared channels, password-change
quarantine, event expiry, bans, logout and provider failures still deny access.

Regression tests use a real participant login and session reference, actual
CMS/Engine/CTF records, and fake external policy, key-store and gateway boundaries.
They verify normal access and denials for another participant, stale assignment,
ended or banned participation, unavailable policy and an undeclared channel.
Mutation checks must detect removal of participant ownership and event-action
selection. Live checks use normal participant access without attack tools.
