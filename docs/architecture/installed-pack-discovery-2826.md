# Discover organization packs in their workspaces

A workspace can list and launch its organization's installed packs when the caller can read content in both scopes. Keep the selected workspace as the range destination and the existing organization adapter binding as the pack configuration. Do not copy or publish the pack.

Resolve and authorize the destination first. Include organization sources only for the same account and organization, with no source workspace. Check organization content read authority before including these sources. Reuse the same registry for listing and launch admission. Other accounts, organizations, and sibling workspace sources remain excluded. Private source and storage details remain omitted from public launch projections.

The launch page uses the existing `agent_requirements` projection. When all three flags are explicitly false, omit the agent picker and send an empty `agents` map through the existing launch API. Missing requirements keep the existing agent selection. Do not create an artificial agent or change the pack. The server continues to validate the source and destination before dispatch.
