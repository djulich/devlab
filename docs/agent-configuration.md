# Agent Configuration

DevLab target repositories configure worker agent invocation in `.devlab/config/agents.toml`.

The operator owns this file. It controls command invocation, role mappings,
models, effort, timeouts, and prompt transport. For a complete first run, use the
[tutorial](tutorial.md); this document is the configuration reference.

Jump to [provider definitions](#provider-definitions),
[precedence](#precedence), [session limits](#session-limits),
[prompt thresholds](#prompt-context-thresholds), or
[smoke tests](#provider-smoke-tests).

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

The `claude` command must already be installed, authenticated, and configured
with the permissions needed by the target workflow. This example leaves model
selection to that CLI. Review executable configuration and smoke-test it before
starting a workflow.

## Role Overrides

Values in `[defaults]` apply to every role. Values in `[roles.<role>]` override
defaults for one role.

Supported roles are:

- `architect`
- `planner`
- `developer`
- `reviewer`
- `integrator`
- `researcher` (optional auxiliary role)

The five software-workflow roles always resolve from `[defaults]` when they do
not have an override. The researcher inherits the requesting architect,
planner, or developer configuration unless `[roles.researcher]` is present.
The clarification resolver always inherits the role that requested the
clarification and is not independently configurable.

For example, extend the minimal configuration to give the architect more time
and use a separate provider for review:

```toml
[roles.architect]
max_session_duration_seconds = 5400

[roles.reviewer]
provider = "review"

[providers.review]
command = "codex"
args = ["--sandbox", "workspace-write", "--ask-for-approval", "never", "exec", "-"]
stdin_template = "{system_prompt}\n\n---\n\n{session_prompt}"
```

This example uses the installed CLIs' model defaults. A different reviewer can
provide another perspective, but does not guarantee independent judgments.

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
- `version_command`: optional provider version command used when recording
  workflow-session metadata. If omitted, DevLab tries
  `<provider-executable> --version`; set it to `""` to skip version discovery.

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
model = "YOUR_MODEL_ID"
effort = "medium"
max_session_duration_seconds = 1200
```

If an unassigned provider has no `[providers.<name>.defaults]`, `--all-providers`
reports it as skipped instead of inventing model or effort values from global
role defaults that may belong to a different provider. Explicit provider checks
fail when DevLab cannot derive an invocation policy from either role assignment
or provider-local defaults.

## Provider Examples

Prefer stdin prompt transport when the CLI supports it: it avoids command-line
length limits and keeps prompt text out of process listings. The command shapes
below illustrate transport; select models available to your account and check
your installed CLI's permission and authentication options before use.

When a template uses `{model}` or `{effort}`, set those values in `[defaults]`
or the applicable `[roles.<role>]` table. Replace `YOUR_MODEL_ID` in examples
with an actual provider model identifier. To use a CLI's native defaults, omit
its model/effort flags, as in the role-override example above.

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

## Model and effort selection

DevLab passes configured strings through the provider's argument or stdin
template. Setting `model` or `effort` alone does not add a provider flag. For
example, `effort` has no effect in the Claude command above because that command
does not reference `{effort}`. Use the provider's own supported syntax rather
than assuming every CLI accepts the same flags or values.

Keep provider-specific values on the relevant roles when combining providers;
global defaults otherwise apply to every role, including a role that overrides
only `provider`.

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

`devlab status --verbose` reports approximate prompt context sizes for each
role. The estimate is intentionally dependency-free and uses roughly four
characters per token.

Configure warning thresholds in `.devlab/config/agents.toml`:

```toml
[prompt_context]
warning_tokens = 60000
critical_tokens = 100000

[prompt_context.roles.planner]
warning_tokens = 50000
critical_tokens = 90000
```

Role-specific thresholds inherit the global values when omitted. If the section
is omitted entirely, DevLab uses `60000` warning tokens and `100000` critical
tokens.
`prompt_context.roles.researcher` is valid and applies while requested research
is awaiting its bounded researcher session.

## Inspection and Validation

Use `devlab status --verbose` to inspect the resolved provider, model, effort,
inactivity timeout, maximum duration, command shape, stdin mode, and approximate
prompt context size for each role. Prompt contents are not printed.

Use `devlab doctor` to validate `.devlab/config/agents.toml` and other workspace
configuration without running agent sessions.

## Executable Configuration Trust

Provider permissions, approval behavior, authentication, network access, and
sandboxing are controlled by the provider and operator. DevLab authorizes the
configured process entry points and freezes their configuration for each run.
See the [authorization reference](operator-guide.md#executable-configuration-authorization)
for digest scope, persistent trust, revocation, CI, and changes during a run.

After reviewing and committing a configuration change:

```bash
devlab trust executable-config
devlab agent-smoke-test
devlab continue --max-sessions 2
```

For a config selected with `--config`, use the same path when authorizing and
smoke-testing it. The trust command displays the effective configuration before
asking for approval. `--show` inspects it without granting trust.

## Provider smoke tests

`devlab agent-smoke-test` starts providers with a tiny prompt to verify command
invocation and prompt transport. It consumes provider usage. By default it tests
the distinct resolved configurations assigned to workflow roles and reports
which roles each check covers.

Use `--role` for one role, `--provider` for one provider, or `--all-providers` to
include unassigned providers that define provider-local defaults. With
`--provider` or `--all-providers`, `--use-provider-defaults` tests those defaults
instead of role-derived policy.

Progress is printed as each check starts and finishes. Logs go under ignored
`.devlab/local/agent-smoke/`, so successful diagnostics do not dirty the target
worktree.

```bash
devlab agent-smoke-test
devlab agent-smoke-test --role developer
devlab agent-smoke-test --provider codex
devlab agent-smoke-test --provider codex --use-provider-defaults
devlab agent-smoke-test --all-providers
devlab agent-smoke-test --all-providers --use-provider-defaults
devlab agent-smoke-test --config .local/live-eval/agents.toml
```

`--root` defaults to the current directory and controls the provider working
directory and log location. `--config` only selects the agent TOML file; it does
not change the workspace root.

## Logging and Failure Diagnostics

DevLab writes per-session agent diagnostics under `.devlab/logs/agents/`:

- `<timestamp>_<session>_<role>.config.toml`: resolved provider, role, model, effort, timeout, command shape, stdin mode, and log paths.
- `<timestamp>_<session>_<role>.stdout.log`: agent stdout.
- `<timestamp>_<session>_<role>.stderr.log`: agent stderr plus DevLab diagnostics for failures that happen before the child process can write output.

Failure reports include the role, failure kind, exit code, timeout when present,
command shape, and log paths. The config log resolves operational placeholders
such as `{model}` and `{effort}`, but leaves `{system_prompt}` and
`{session_prompt}` unexpanded so prompt contents are not written there.

By default, DevLab does not retain full prompts. For debugging, run with `devlab
continue --retain-prompts` to write split prompt logs next to the agent
invocation logs:

- `<timestamp>_<session>_<role>.base-prompt.md`
- `<timestamp>_<session>_<role>.session-prompt.md`

The matching `.config.toml` includes `base_prompt_log` and `session_prompt_log`
paths when prompt retention is enabled. Treat `.devlab/logs/agents/` as
sensitive: agent output and retained prompts may contain target project details.
