# Issue a GCP operator credential from the cluster

Operator commands such as `experiment_batch` and `experiment_dispatch` need a native bearer credential file.
A portal session normally issues this personal token.
When no portal session is available, a cluster operator can issue one in the portal container.

This procedure requires GKE access to the deployment cluster.
That access already permits any change to the application, so this procedure adds no new authority.

## Issue the credential

1. Get Connect Gateway credentials in a separate kubeconfig:

   ```bash
   KUBECONFIG=/tmp/tenant-check gcloud container fleet memberships get-credentials <cluster> --project <project>
   ```

2. Select one running `portal-web` pod in the `shifter-platform` namespace.
3. Copy this script to `/tmp/issue_operator_token.py` in the pod's `portal` container:

   ```python
   import os
   from datetime import timedelta

   from django.contrib.auth import get_user_model
   from django.db import transaction
   from django.utils import timezone

   from management.principals import human_principal_user_id
   from shared.api_tokens.audit import TokenEvent, record_token_event
   from shared.api_tokens.models import ApiToken
   from shared.api_tokens.scopes import AUTHORIZATION_ACTION_SCOPES
   from shared.identity_scope import PrincipalRef
   from workspaces.services import get_identity_cutover_state

   state = get_identity_cutover_state()
   if state is None or state.state != "activated" or state.bootstrap_principal_uuid is None:
       raise SystemExit("identity is not activated")
   principal = PrincipalRef(state.bootstrap_principal_uuid, "human")
   user = get_user_model().objects.get(pk=human_principal_user_id(principal))
   with transaction.atomic():
       token, raw = ApiToken.create_token(
           name="operator-experiment-dispatch",
           created_by=user,
           scopes=sorted(AUTHORIZATION_ACTION_SCOPES.values()),
           expires_at=timezone.now() + timedelta(hours=12),
       )
       record_token_event(TokenEvent.CREATED, token_id=token.token_id, token_pk=token.pk,
                          actor_principal_uuid=principal.uuid, context="operator-cli")
   fd = os.open("/tmp/operator-token", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
   with os.fdopen(fd, "w") as stream:
       stream.write(raw)
   print("issued", token.token_id, "expires", token.expires_at.isoformat())
   ```

4. Run it through the image entrypoint, which loads the runtime secrets:

   ```bash
   kubectl -n shifter-platform exec <pod> -c portal -- \
     /app/entrypoint.sh sh -c 'python manage.py shell < /tmp/issue_operator_token.py'
   ```

The script issues the token to the recorded bootstrap administrator.
The token has every `authorization:` scope and expires after 12 hours.
Live application policy still applies to each action.
The token goes only to `/tmp/operator-token` in that container, with mode `0600`.
The script prints the public token ID, not the token.

## Use the credential

Run the operator commands in the same container, through the entrypoint.
Pass `--credential-file /tmp/operator-token`.
A restarted pod loses the file.

## Revoke the credential

Revoke the token when the operator work ends.
Run this in the same container, through the entrypoint, with the printed token ID:

```python
from shared.api_tokens.audit import TokenEvent, record_token_event
from shared.api_tokens.models import ApiToken
from workspaces.services import get_identity_cutover_state

token = ApiToken.objects.get(token_id="<token ID>")
token.revoke()
record_token_event(TokenEvent.REVOKED, token_id=token.token_id, token_pk=token.pk,
                   actor_principal_uuid=get_identity_cutover_state().bootstrap_principal_uuid,
                   context="operator-cli")
```

Then delete `/tmp/operator-token`.
