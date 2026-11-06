# Session cleanup gateway access (#2837)

The maintenance command revalidates retained gateway sessions and closes sessions
that no longer have access. Its first heartbeat follows that cleanup pass.
The existing chart permits gateway API traffic from the portal only. Blocked
cleanup requests can prevent the maintenance worker from becoming ready.

Use the existing Helm NetworkPolicy boundary under ADR-006 and ADR-007.
Add two rules: ingress to gateway pods and egress from session cleanup pods.
Both rules select exact component labels in the same namespace and TCP 8080.
Keep default deny and the existing portal rules. Other workers gain no access.
No new endpoint, credential, configuration setting or health exception is needed.

Session tokens remain in the existing retained records and request headers.
The gateway continues to validate them. A network rule cannot grant a user
access or mark a session closed. Cleanup must receive its normal native response.

Verify both rendered rules with exact selectors and ports. Remove each rule in
turn to check the tests. Review the complete GCP render diff before changing
its saved hashes. Check the existing gateway path without credentials in Test,
then confirm that the worker completes cleanup and produces its heartbeat.
Do not update the customer tenant without approval.
