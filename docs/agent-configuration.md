# Agent Configuration

DevLab target repositories configure worker agent invocation in `.devlab/config/agents.toml`.

This file is target-owned and intended to be edited by the human operator. It controls which provider, command, model, effort level, timeout, and prompt transport are used for each DevLab role.

## Minimal Example

```toml
[defaults]
provider = "default"
max_session_duration_seconds = 3600
# inactivity_timeout_seconds = 600

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
max_session_duration_seconds = 3600

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

For ordinary workflow sessions DevLab also supplies process environment needed by
the submission protocol. `DEVLAB_SESSION_ENVELOPE` identifies the trusted active
session envelope, and `DEVLAB_PYTHON` identifies the interpreter running DevLab so
the role can submit its initialized candidate with
`"$DEVLAB_PYTHON" -m devlab.cli session handoff submit`. Provider commands do not
need to template these values into their arguments, but the invoked agent must be
able to edit the target workspace and run the local submission command.

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
max_session_duration_seconds = 1200
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
max_session_duration_seconds = 3600

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

## Session Limits

`max_session_duration_seconds` bounds total provider runtime.
`inactivity_timeout_seconds` independently bounds time with no bytes received on
either provider stdout or stderr. It is opt-in: omission leaves silence unbounded.

Set either limit to the string `"none"` to disable an inherited value. Durations
must otherwise be positive integers; zero, negative values, and booleans are
invalid. With no maximum, a provider that keeps producing output can run
indefinitely.

Inactivity observes bytes, not semantic progress. A noisy retry loop remains
active, while a healthy command that emits nothing can reach the inactivity
limit. On either limit DevLab terminates the local provider process group with a
bounded grace period, but detached descendants and remote or container side
effects may remain and are handled by the existing recovery workflow.

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

Use `devlab status --verbose` to inspect the resolved provider, model, effort,
inactivity timeout, maximum duration, command shape, stdin mode, and approximate
prompt context size for each role. Prompt contents are not printed.

Use `devlab doctor` to validate `.devlab/config/agents.toml` and other workspace configuration without running agent sessions.

## Executable Configuration Trust

DevLab does not interpret provider permission, approval, authentication,
network, or sandbox options. Those policies are provider-native and
operator-owned.

Before an operator-facing command starts a provider or profile lifecycle
command, DevLab builds a canonical snapshot of effective provider configuration,
role mappings, invocation overrides, and profile lifecycle configuration. It
fingerprints and freezes that parsed snapshot for the command. Formatting and
comment-only TOML changes do not change the digest; executable values and
provider/model/effort overrides do.

Inspect and approve the current snapshot:

```bash
devlab trust executable-config --show
devlab trust executable-config
```

Trust is stored outside the target repository in user-local DevLab state and is
scoped to the canonical workspace, agent-config source, and digest. A target
repository cannot carry its own operator trust record. Editing executable
configuration produces a new digest and requires another approval. A profile-changing
task may finish review with the command's frozen snapshot, but DevLab then stops
before preparing a session outside that task cycle. Review and authorize the new
snapshot, then start a fresh command; DevLab never adopts it in place:

```bash
devlab trust executable-config --revoke
```

Profile default-validation commands are executable configuration alongside lifecycle
commands. Changes to either alter the fingerprint.

Unattended CI can require an independently approved full digest:

```bash
devlab implement --unattended \
  --require-exec-config-digest "$APPROVED_DEVLAB_EXEC_DIGEST"
```

The expected value should come from protected CI or runner configuration, not an
ordinary target-repository file. An externally contained or disposable
environment may explicitly accept the current snapshot for one invocation:

```bash
devlab implement --unattended --accept-current-exec-config
```

This does not create persistent trust. DevLab records the digest and
authorization source and still freezes the snapshot. Trust covers configured
process entry points only; it does not cover the implementation or transitive
behavior of commands such as `make setup`, nor does it contain a process after
launch.

Use `devlab agent-smoke-test` to start configured providers with a tiny prompt and verify that commands, templated arguments, and prompt transport work. By default, it tests the distinct provider configurations assigned to workflow roles, reports which roles use each checked provider, prints progress as each check starts and finishes, and writes stdout/stderr logs under the ignored `.devlab/local/agent-smoke/` directory so the diagnostic does not dirty the target worktree. Use `--provider <name>` to select one provider, or `--all-providers` to also test unassigned provider entries that have provider-local defaults. Add `--use-provider-defaults` with `--provider` or `--all-providers` to test `[providers.<name>.defaults]` directly instead of role-derived policy.

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
