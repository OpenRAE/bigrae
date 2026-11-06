# Retry a failed native cleanup task

A cleanup worker can fail before it reports a terminal result. The range then stays in the destroying state. Repeating an authorized cleanup request must be able to resume that retained work without treating missing evidence as successful absence.

Keep the existing cleanup authority and range transaction. The existing privileged launcher checks delivered cleanup intents at most once per minute. The web portal retains its existing queue-only role and never calls the cluster. For a duplicate cleanup intent whose launch delivery completed, the launcher queries the existing task runner with its recorded task reference. Permit a fresh attempt only when the provider reports FAILED and the task runner accepts terminal cleanup of the exact recorded image, command, service account, container, and task identity. Unknown, missing, successful, running, or mismatched tasks retain the current operation.

After that check, clear only the operation reservation under the existing range lock and use the normal launch queue to reserve a fresh operation. Keep immutable earlier inputs and results, the range identity, original cloud baseline, and resource generation. The new reservation occurs in the same transaction, so a concurrent or repeated request cannot queue a second retry.

A compare-and-set scheduling update claims each due observation before provider calls. Current destroying range and cleanup intent filters exclude settled or superseded operations. Provider observation and terminal task removal use the existing cloud port and its bounded calls. They occur only on this exceptional duplicate-cleanup path while the target lock prevents competing retries. No migration, new credential, API option, result fabrication, or direct provider resource deletion is introduced. Only a later verified cleanup result can release project custody.

Tests cover failed-task retry, normal duplicate requests, concurrent reservation changes, unknown and active tasks, identity refusal, and unchanged cleanup authority.
