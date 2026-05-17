# Store workflow state in repository files

DevLab stores durable workflow state in repository files rather than conversational memory, process-local state, or an external database. This keeps agent sessions resumable, reviewable, provider-independent, and easy for humans to inspect. The trade-off is that DevLab must carefully own file formats and state transitions through trackers and workspace abstractions instead of relying on hidden runtime coordination.
