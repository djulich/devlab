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
args = ["-p", "--system-prompt", "{system_prompt}", "{session_prompt}"]
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
args = [
  "-p",
  "--model", "{model}",
  "--thinking", "{effort}",
  "--system-prompt", "{system_prompt}",
  "{session_prompt}",
]
```

Fields:

- `command`: executable name or command prefix.
- `args`: ordered command arguments. These may include provider options and prompt placeholders.
- `stdin_template`: optional template used to send prompts through standard input. When set, DevLab treats stdin as the prompt transport; otherwise prompt placeholders should appear in `args`.
- `version_command`: optional provider version command used when recording session metadata during `devlab run`. If omitted, DevLab tries `<provider-executable> --version`; set it to `""` to skip version discovery.
- `timeout_seconds`: optional role/session command timeout.

Supported placeholders:

- `{role_name}`
- `{provider}`
- `{model}`
- `{effort}`
- `{system_prompt}`
- `{session_prompt}`

`{system_prompt}` is DevLab's generated standing prompt for the role: packaged
conventions, role instructions, applicable domain overlays, and tooling policy.
Provider flags such as Claude's `--system-prompt` are provider-specific transport
options; they are not DevLab placeholder names.

## Provider Examples

Prefer stdin prompt transport when your agent CLI supports it. Stdin avoids command-line length limits and keeps prompt text out of process listings.

### Codex-style stdin prompt

```toml
[providers.codex]
command = "codex"
args = ["--model", "{model}", "-c", "model_reasoning_effort=\"{effort}\"", "exec", "-"]
stdin_template = "{system_prompt}\n\n---\n\n{session_prompt}"
```

### Pi-style command-line prompts

```toml
[providers.pi]
command = "pi"
# Pi uses --thinking for the effort level. When using OpenAI subscription/Codex
# models, pass the provider explicitly so Pi does not resolve the model through
# an unauthenticated provider.
args = [
  "-p",
  "--provider", "openai-codex",
  "--model", "{model}",
  "--thinking", "{effort}",
  "--system-prompt", "{system_prompt}",
  "{session_prompt}",
]
```

### Claude-style command-line prompts

```toml
[providers.claude]
command = "claude"
args = ["-p", "--model", "{model}", "--system-prompt", "{system_prompt}", "{session_prompt}"]
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

## Prompt Context Thresholds

`devlab status --verbose` reports approximate prompt context sizes for each role. The estimate is intentionally dependency-free and uses roughly four characters per token.

Configure warning thresholds in `.devlab/config/agents.toml`:

```toml
[prompt_context]
warning_tokens = 60000
critical_tokens = 100000

[prompt_context.roles.planner]
warning_tokens = 50000
critical_tokens = 90000
```

Role-specific thresholds inherit the global values when omitted. If the section is omitted entirely, DevLab uses `60000` warning tokens and `100000` critical tokens.

## Inspection and Validation

Use `devlab status --verbose` to inspect the resolved provider, model, effort, timeout, command shape, stdin mode, and approximate prompt context size for each role. Prompt contents are not printed.

Use `devlab doctor` to validate `.devlab/config/agents.toml` and other workspace configuration without running agent sessions.

Use `devlab agent-smoke-test` to start the configured providers with a tiny prompt and verify that commands, templated arguments, and prompt transport work. It tests all roles by default and writes stdout/stderr logs under `.devlab/logs/agents/`.

```bash
devlab agent-smoke-test
devlab agent-smoke-test --role developer
devlab agent-smoke-test --config .local/live-eval/agents.toml
```

`--root` defaults to the current directory and controls the provider working directory and log location. `--config` only selects the agent TOML file; it does not change the workspace root.

## Logging and Failure Diagnostics

DevLab writes per-session agent diagnostics under `.devlab/logs/agents/`:

- `<timestamp>_<session>_<role>.config.toml`: resolved provider, role, model, effort, timeout, command shape, stdin mode, and log paths.
- `<timestamp>_<session>_<role>.stdout.log`: agent stdout.
- `<timestamp>_<session>_<role>.stderr.log`: agent stderr plus DevLab diagnostics for failures that happen before the child process can write output.

Failure reports include the role, failure kind, exit code, timeout when present, command shape, and log paths. The config log resolves operational placeholders such as `{model}` and `{effort}`, but leaves `{system_prompt}` and `{session_prompt}` unexpanded so prompt contents are not written there.

By default, DevLab does not retain full prompts. For debugging, run with `devlab run --retain-prompts` to write split prompt logs next to the agent invocation logs:

- `<timestamp>_<session>_<role>.base-prompt.md`
- `<timestamp>_<session>_<role>.session-prompt.md`

The matching `.config.toml` includes `base_prompt_log` and `session_prompt_log` paths when prompt retention is enabled. Treat `.devlab/logs/agents/` as sensitive: agent output and retained prompts may contain target project details.
