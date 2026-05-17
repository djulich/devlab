# Split workspace mutations from snapshots

`Workspace` is the target-workspace mutation boundary; `WorkspaceSnapshot` is a cached read-only view. This avoids repeated cross-tracker parsing without turning snapshots into hidden mutable state. Workspace mutations invalidate the cached snapshot; external file changes are observed with a new `Workspace`.
