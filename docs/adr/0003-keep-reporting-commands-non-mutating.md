# Keep reporting commands non-mutating

`status`, `doctor`, prompt assembly, and prompt context reporting must only observe state; they must not sync, repair, create, or transition workflow files. This makes inspection safe and predictable, at the cost of requiring explicit workflow or repair commands for mutations.
