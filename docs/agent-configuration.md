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

Provider sections describe how DevLab invokes a CLI agent. They own transport mechanics:
the executable, arguments, stdin prompt transport, and version discovery. Invocation policy
such as model, effort, and timeout normally comes from `[defaults]` and `[roles.<role>]`.

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
- `version_command`: optional provider version command used when recording session metadata during `devlab implement`. If omitted, DevLab tries `<provider-executable> --version`; set it to `""` to skip version discovery.

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

Provider-local defaults are optional. They are used when a provider is smoke-tested
outside a role context, for example with `devlab agent-smoke-test --provider codex`
when no role currently uses `codex`, or with `--all-providers` for unassigned
providers. Use `--use-provider-defaults` to test provider-local defaults even
when the provider is assigned to roles.

```toml
[providers.codex.defaults]
model = "gpt-5.5"
effort = "medium"
timeout_seconds = 1200
```

If an unassigned provider has no `[providers.<name>.defaults]`, `--all-providers`
reports it as skipped instead of inventing model or effort values from global
role defaults that may belong to a different provider. Explicit provider checks
fail when DevLab cannot derive an invocation policy from either role assignment
or provider-local defaults.

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

Resolved role settings use this precedence:

1. CLI overrides for the current run.
2. Role-specific values in `.devlab/config/agents.toml`.
3. Defaults in `.devlab/config/agents.toml`.
4. DevLab built-in fallback defaults.

Provider-local defaults do not participate in normal role resolution. They only provide
invocation policy for provider smoke tests that are not based on an assigned role.

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

Use `devlab agent-smoke-test` to start configured providers with a tiny prompt and verify that commands, templated arguments, and prompt transport work. By default, it tests the distinct provider configurations assigned to workflow roles, reports which roles use each checked provider, prints progress as each check starts and finishes, and writes stdout/stderr logs under `.devlab/logs/agents/`. Use `--provider <name>` to select one provider, or `--all-providers` to also test unassigned provider entries that have provider-local defaults. Add `--use-provider-defaults` with `--provider` or `--all-providers` to test `[providers.<name>.defaults]` directly instead of role-derived policy.

```bash
devlab agent-smoke-test
devlab agent-smoke-test --role developer
devlab agent-smoke-test --provider codex
devlab agent-smoke-test --provider codex --use-provider-defaults
devlab agent-smoke-test --all-providers
devlab agent-smoke-test --all-providers --use-provider-defaults
devlab agent-smoke-test --config .local/live-eval/agents.toml
```

`--root` defaults to the current directory and controls the provider working directory and log location. `--config` only selects the agent TOML file; it does not change the workspace root.

## Logging and Failure Diagnostics

DevLab writes per-session agent diagnostics under `.devlab/logs/agents/`:

- `<timestamp>_<session>_<role>.config.toml`: resolved provider, role, model, effort, timeout, command shape, stdin mode, and log paths.
- `<timestamp>_<session>_<role>.stdout.log`: agent stdout.
- `<timestamp>_<session>_<role>.stderr.log`: agent stderr plus DevLab diagnostics for failures that happen before the child process can write output.

Failure reports include the role, failure kind, exit code, timeout when present, command shape, and log paths. The config log resolves operational placeholders such as `{model}` and `{effort}`, but leaves `{system_prompt}` and `{session_prompt}` unexpanded so prompt contents are not written there.

By default, DevLab does not retain full prompts. For debugging, run with `devlab implement --retain-prompts` to write split prompt logs next to the agent invocation logs:

- `<timestamp>_<session>_<role>.base-prompt.md`
- `<timestamp>_<session>_<role>.session-prompt.md`

The matching `.config.toml` includes `base_prompt_log` and `session_prompt_log` paths when prompt retention is enabled. Treat `.devlab/logs/agents/` as sensitive: agent output and retained prompts may contain target project details.
