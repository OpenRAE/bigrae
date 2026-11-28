# Team invite codes (CTF-504, issue 647)

One team has one current code. A successful join can spend that code once or leave it available to other eligible participants.
The database transaction that changes membership decides which join succeeds.
This note records the design against revision `ac074ac13`.

## Ownership and compatibility

Keep the code and its settings on `CTFTeam`. Keep issuance and redemption in `ctf.services.team`.
Keep the globally unique field. Use one CTF code generator backed by `secrets.token_urlsafe(16)` for creation and rotation.
Retain existing code values, case, uniqueness across soft-deleted rows, and the 32-character storage limit.

The published join request accepts up to 64 characters and trims surrounding whitespace.
Preserve that input contract and opaque lookup, including for older stored values.

The proposed policy owner is the captain. Offer optional use mode and lifetime on the existing regeneration action.
Changing either setting issues a new code. Existing teams and ordinary team creation start with multi-use codes without a deadline.

An omitted setting retains its current value. A null lifetime explicitly removes expiry.
A finite lifetime is a positive whole number of seconds within database and timestamp bounds.
Each rotation starts the selected lifetime again, including after expiry.
An empty request body and the SPA's `{}` both remain valid.

Record the deadline as an aware instant and consumption as a fact about the current code.
Rotation replaces the code, sets its new deadline, and clears consumption together.
Take the issuance time from the server. A rename or score update must never extend the deadline.
An additive Django migration gives existing rows compatible defaults without minting new codes.

All portal processes serving joins must enforce the settings before captains can issue restricted codes.
Rolling back to an older reader while restricted codes exist loses that enforcement.

## Redemption and authority

The data flow runs from the participant browser or API client through authenticated DRF, the CTF team service, and PostgreSQL.
Only the refreshed participant projection returns to the caller.

- Preserve session CSRF, bearer resolution in `config/_drf_settings.py`, and temporary-account restrictions in `CTFAccountBoundaryMiddleware`.
  Keep `CTF_PARTICIPANT_PERMISSIONS`, play read/write scopes, and the active-event `event.participate` mapping in `ctf.api.operation_policy`.
  For secret-bearing reads and writes, reuse `_require_admitted_participant` for the current credential, event ceiling, and live policy decision.
  Preserve its failure mapping. Resource selection from the active event alone does not establish that decision.
- Use `_load_participant`, `assert_participant_can_compete`, and the service's team-mode check for mutations.
  Resolve the team through the live manager in the acting participant's event.
  Use `_require_captain` for rotation. Recheck eligibility, live membership, and captain authority on the refreshed rows before writing.
- A code lookup locates a candidate. Inside the existing atomic join, use `_lock_team` with the joining participant.
  Keep its ordered participant locks, NOWAIT conflict handling, team lock, and membership snapshot check.
  Compare the submitted code with the locked row and check its consumption and deadline there.
  Sample `timezone.now()` after locking. Equality with the deadline counts as expired.
  `ctf.services.submission_receipts.revalidate_receipt_for_commit` uses this same deadline rule.
  `shared.db.ExpiringStateMixin.is_expired` uses a strict greater-than comparison and describes expiry of the whole model.
- Check current membership and `is_full` under the lock. Spend a single-use code only for a successful membership change.
  Preserve the existing team-switch path, old and new team score updates, and position reconciliation in the transaction.
  A refusal or rollback preserves membership and code state. Leaving the team never restores a spent use.
  Organizer seat assignment in `participant.lifecycle.add_participant` enforces capacity independently and spends no code.

Return current team state to direct service callers. An object loaded during the initial lookup can contain obsolete invite data.
Use the normal `CTFBaseModel.save` path, including `full_clean`, and limit updates to the fields that changed.
Keep structural invariants in the persisted state. Check time when issuing or redeeming, since an expired row must remain valid to save.

An empty `invite_code` triggers generation on save. Use a consumption marker so spending a code never mints another.
Handle a generation collision at issuance without echoing the code or classifying an unrelated database failure as a duplicate team name.

## API, browser, and diagnostics

| Boundary | Design constraint |
| --- | --- |
| Request | Keep `TeamJoinRequestSerializer` and the current join media types. Give regeneration its own optional DRF input fields. Use the shared `ClosedSerializer` and bounded `ClosedJSONParser` for the new JSON settings. Preserve legacy empty submissions, including an empty form. Reject unknown settings, duplicate JSON members, invalid modes and invalid lifetimes before rotation. Only the server sets consumption and deadlines. |
| Contract | Use `extend_schema`, `ParticipantTeamSerializer`, and the existing v1 operation IDs. ADR-040 permits optional additions. Follow the output-field precedent in `ctf/api/serializers/participant.py` because the generator marks read-only fields required. Check the optional request body and output in `openapi/v1.json` and `frontend/src/api/schema.d.ts` through `npm run gen:api`. |
| Disclosure | Use one code-validity rule for the locked decision and display. In `projections.participant_team`, return the usable code only to the current captain of the live team. Return null for everyone else and for expired or spent codes. Keep captain settings out of other projections. Apply the existing `add_never_cache_headers` pattern to team responses carrying secrets, including mutation responses. |
| SPA | In `TeamPage.tsx`, show regeneration to the captain even when the code is null. Use `useRegenerateTeamCode`, `useTeamMutation`, `apiFetch`, and generated request types. Keep existing query invalidation and disabled-pending controls. A cached display can outlive the code. Refresh after an uncertain result and keep automatic mutation retries disabled. |
| Failures | Use `CTFNotFoundError` for unknown, foreign-event, replaced, spent, or expired codes. `ctf_error_response` maps all five to the same safe 404. Keep input, permission, and membership conflicts on the existing 400, 403, and 409 paths. `shared.api.errors` owns safe field details and request IDs. |
| Observability | Use the team logger and bounded actor, team, event, and request IDs. Exclude codes from exceptions, SQL parameters in diagnostic output, request logs, audit payloads, metrics, URLs, and persistent browser storage. Legacy Django admin definitions name the code. Production mounts `config.policy_admin_site`, which does not register teams. Keep these surfaces separate. |

## Evidence and scope

Use the real service and HTTP fixtures in `tests/ctf/test_team_api.py`.
Cover migration compatibility, both use modes, exact expiry, rotation after consumption or expiry, and failure without consumption.
Exercise wrong-event, deleted, ineligible, full, already-joined, and former-captain cases.
Check secret redaction on reads, mutation responses, errors, and logs.
Use `TeamPage.test.tsx` and the team mutation tests for settings, recovery, and cache refresh.

Follow `test_team_captain_concurrency.py` with independent PostgreSQL connections and controlled overlap.
Prove one winner for two eligible joiners using one code, with capacity available to both.
Cover both orderings of rotation and redemption, expiry between lookup and lock, rollback, and replay after a lost response.
Inspect committed membership and code state. Targeted mutation checks should detect a removed locked comparison, consumption check, or inclusive deadline.

The configuration seam is the captain's issuance request and the team's stored use mode and lifetime.
It supports another lifetime without editing a constant or adding a join path.

The code grants team membership within existing event admission. Account creation, workspace invitations, team passwords, and message delivery have different owners.
Workspace invitations check a verified recipient identity and a signed generation. A hash alone cannot reproduce the code for an authorized captain.
This change needs no token history, receipt ledger, background expiry job, or new policy grant.
The environment manifest, secret bindings, OS arguments, Helm, Terraform, and cloud IAM receive no invite data.

## Deployment and rollout

The migration gives the two new non-null boolean columns a database default of
`false`. A prior-release replica that omits the columns from a team insert still
writes a valid row during a rolling upgrade. The nullable lifetime and deadline
columns default to null, so prior-release inserts stay valid too.

Enforcement and issuance ship in one release. A prior-release replica cannot
enforce columns it does not know, so it can redeem a spent or expired code while
both revisions serve traffic. This window is bounded: the fleet reaches full
enforcement when the rollout completes, and the team size limit still holds on
every replica. Keep a rollback target on an enforcing build. If the operator must
restore a prior-release build while restricted codes exist, regenerate the
affected codes without restrictions first.

ADR-001, ADR-019, ADR-029, ADR-040, and ADR-066 cover the existing boundaries.
Keep the import rules in `.importlinter` and `scripts/check_layer_imports/layer_imports.yaml`.
The repository's `.gc/plan-rules.md` and `.github/workflows/_quality.yml` define the architecture and contract checks.
