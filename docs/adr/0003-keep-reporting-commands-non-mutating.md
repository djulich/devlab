# Keep reporting commands non-mutating

`status`, `doctor`, prompt assembly, and prompt context reporting must only observe state; they must not sync, repair, create, or transition workflow files. This makes inspection safe and predictable, at the cost of requiring explicit workflow or repair commands for mutations.

Shell completion has the same observation-only contract. The CLI constructs its
parser and handles argcomplete requests before importing workflow command
handlers. Completion may list local paths but must not execute providers, Git,
profile commands, or workflow operations. `devlab completion bash|zsh` only emits
shell registration code; it does not edit shell configuration or workspace files.
