# Read status from the normal Job resource

The Kubernetes Job resource contains its status and workload identity. Use the existing Job read permission for task observation and identity-checked completed-task removal. Do not call the separate status subresource or add a permission for it.

Keep the same namespace binding, request timeout, unknown and failed-state rules, and exact image, command, service account, container, and task identity checks. Regression tests deny status-subresource reads while allowing normal Job reads.
