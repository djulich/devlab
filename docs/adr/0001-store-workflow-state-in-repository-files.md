# Store workflow state in repository files

DevLab stores workflow state in repository files, not conversational memory, process-local state, an external database, or an external tracker. This makes sessions resumable, inspectable, and provider-independent, at the cost of owning simple file formats and explicit state transitions.
