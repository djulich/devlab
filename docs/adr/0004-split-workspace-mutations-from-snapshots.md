# Split workspace mutations from snapshots

DevLab separates `Workspace`, the target-workspace mutation boundary, from `WorkspaceSnapshot`, a cached read-only view of workflow state. This keeps cached cross-tracker reads efficient without turning the workspace into hidden mutable workflow memory. Mutating workspace handles invalidate the lazy snapshot, while external file changes are observed by creating a new `Workspace` instance.
