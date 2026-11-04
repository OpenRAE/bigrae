# Supervised range power

Organizers can request a pause or resume of an assigned CTF range through a
recorded human review. The installation must enable the participant control
service, and an organization administrator must configure the source mapping.

This feature supports qualified GCE ranges with dedicated persistent disks.
It does not preserve RAM or freeze time, people, or external services. Other
backends and unsupported resource layouts are refused.

## Configure a source

Open the source's pack binding in the administration console. Under **Supervised
range power**, enter the participant, controller, pause action, resume action,
and observation boundary addresses supplied by the pack author. Review and save
the mapping. BigRAE checks these logical references against the displayed pack
version. This step does not install executable code or change a running range.

A pack or control policy change requires a reviewed mapping update. The service
refuses configuration replacement while an active range uses that mapping.

## Request an operation

1. Open the organizer's participant detail page.
2. Under **Supervised range power**, activate the configured mapping for the
   assigned range. Activation does not change its power state.
3. Select **Propose pause** or **Propose resume** and confirm the request.
4. Review the recorded proposal and select **Approve** or **Deny**. Approval
   requires a currently authorized human identity. A service identity can propose
   or consume approved work, but cannot provide the human approval.
5. Select **Request reviewed pause** or **Request reviewed resume** on the
   recorded approval, then confirm the effect.
6. Check **Native range status**. An admitted review or action does not establish
   that the cloud operation succeeded. Resume also requires guest access and
   composition checks before the range becomes ready.

The service checks the original requester, human reviewer, and consumer's
current permissions. The same person may hold these roles; this feature does
not enforce a two-person rule. Recorded requests show history, rather than a
promise that an earlier approval is still usable. Cancellation and later review
changes can prevent an effect even when its earlier admission succeeded.

## Recover a response

If a confirmation fails, submitting it again retains its original request and
review context. Use **Retry original request** beside a recorded request to
recover its receipt. This cannot replace its arguments or move it to a newer
review context. Refresh the displayed status before making a new decision.
**Earlier requests** loads older records; **Latest requests** returns to the
most recent page.

A failed or uncertain cloud response may require operator investigation. Do not
assume a timeout or cancellation reversed an operation. The platform fences
uncertain calls and uses independent readback before allowing later control.
The authorized range destruction path remains available for containment, with
its normal resource cleanup checks.

See the [operator guide](../ops/supervised-range-power.md) for deployment,
recovery, and evidence limits.
