# Keep reporting commands non-mutating

DevLab reporting and validation paths such as `status`, `doctor`, prompt assembly, and prompt context reporting must not create, repair, sync, or transition workflow state. This keeps observation safe and predictable: users can inspect a target workspace without accidentally advancing or rewriting it. Mutations belong to explicit workflow paths such as `devlab run` or future commands whose purpose is repair or synchronization.
