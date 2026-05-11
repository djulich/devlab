# Agent Configuration

DevLab target repositories configure worker agent invocation in `.devlab/config/agents.toml`.

This file is target-owned and intended to be edited by the human operator. It controls which provider, command, model, effort level, timeout, and prompt transport are used for each DevLab role.

## Minimal Example

```toml
[defaults]
provider = "default"
timeout_seconds = 3600

[providers.default]
command = "claude"
args = ["-p"]
prompt_args = ["--system-prompt", "{system_prompt}", "{session_prompt}"]
```

## Role Overrides

Values in `[defaults]` apply to every role. Values in `[roles.<role>]` override defaults for one role.

Supported roles are:

- `architect`
- `planner`
- `developer`
- `reviewer`
- `integrator`

Example:

```toml
[defaults]
provider = "pi"
model = "gpt-5-codex"
effort = "medium"
timeout_seconds = 3600

[roles.architect]
model = "gpt-5"
effort = "high"

[roles.reviewer]
provider = "claude"
model = "claude-sonnet-4.5"
effort = "high"
```

## Provider Definitions

Provider sections describe how DevLab invokes a CLI agent.

```toml
[providers.pi]
command = "pi"
args = ["-p", "--model", "{model}", "--effort", "{effort}"]
prompt_args = ["--system-prompt", "{system_prompt}", "{session_prompt}"]
```

Fields:

- `command`: executable name or command prefix.
- `args`: fixed or templated command arguments before prompt arguments.
- `prompt_args`: arguments used to pass prompts on the command line.
- `stdin_template`: optional template used to send prompts through standard input instead of command-line arguments.
- `timeout_seconds`: optional role/session command timeout.

Supported placeholders:

- `{role_name}`
- `{provider}`
- `{model}`
- `{effort}`
- `{system_prompt}`
- `{session_prompt}`

## Provider Examples

### Pi-style command-line prompts

```toml
[providers.pi]
command = "pi"
args = ["-p", "--model", "{model}", "--effort", "{effort}"]
prompt_args = ["--system-prompt", "{system_prompt}", "{session_prompt}"]
```

### Claude-style command-line prompts

```toml
[providers.claude]
command = "claude"
args = ["-p", "--model", "{model}"]
prompt_args = ["--system-prompt", "{system_prompt}", "{session_prompt}"]
```

### Codex-style stdin prompt

```toml
[providers.codex]
command = "codex"
args = ["exec", "-", "--model", "{model}"]
stdin_template = "{system_prompt}\n\n---\n\n{session_prompt}"
prompt_args = []
```

## Suggested Split-Brain Review Setup

To reduce shared blind spots, use a different reviewer provider or model from the developer.

```toml
[defaults]
provider = "pi"
model = "gpt-5-codex"
effort = "medium"
timeout_seconds = 3600

[roles.developer]
provider = "codex"
model = "gpt-5-codex"

[roles.reviewer]
provider = "claude"
model = "claude-sonnet-4.5"
effort = "high"
```

## Precedence

Resolved agent settings should use this precedence:

1. CLI overrides for the current run.
2. Role-specific values in `.devlab/config/agents.toml`.
3. Defaults in `.devlab/config/agents.toml`.
4. DevLab built-in fallback defaults.

## Inspection and Validation

Use `devlab status --verbose` to inspect the resolved provider, model, effort, timeout, command shape, and stdin mode for each role. Prompt contents are not printed.

Use `devlab doctor` to validate `.devlab/config/agents.toml` and other workspace configuration without running agent sessions.

## Logging

DevLab logs resolved agent configuration for each session under `.devlab/logs/agents/`.

The log includes provider name, role, model, effort, timeout, and rendered command shape, but does not include full system or session prompts.
