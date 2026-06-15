# Agent Smoke Test Review Handoff

Date: 2026-06-15

## Context

Recent work changed `devlab agent-smoke-test` from role-only checks toward provider-config checks:

- Previous commit `332d033`: default smoke test briefly checked all configured providers.
- Previous commit `98d5eab`: default changed to distinct role-assigned provider configs, with `--all-providers` for broader checks.
- Current staged work refines this further:
  - smoke tests now operate on provider-config targets, not separate role/provider/workflow scopes;
  - `scope` was removed from smoke results;
  - `[providers.<name>.defaults]` was introduced for unassigned provider smoke checks;
  - `--provider <name>` selects provider configs by provider name;
  - `--all-providers` checks role-assigned provider configs plus unassigned providers that have provider-local defaults;
  - unassigned providers without provider-local defaults are reported as skipped;
  - timeout is not part of the deduplication key; grouped configs use the smallest non-null timeout.

Validation before this handoff:

- `uv --cache-dir /tmp/uv-cache run ruff check` passed.
- `uv --cache-dir /tmp/uv-cache run pytest` passed with `367 passed, 4 skipped`.

## Review Findings

### 1. Reported command can differ from the command actually executed

In `src/devlab/agent_smoke.py`, smoke invocation uses:

- `AgentInvocation.role_name = target.check_name`

but `format_agent_smoke_report()` prints:

- `config.command`

That `config.command` was rendered from a representative role config before the smoke invocation. If provider args contain `{role_name}`, the actual command rendered by `CliAgentProvider.invoke()` can use the smoke check name, while the report still shows the representative role name.

Suggested simplification:

- In the smoke report, print `agent_result.command` instead of `config.command`.
- `AgentResult.command` is already the redacted command actually used by the provider.

### 2. Explicit `--provider` can exit successfully without testing anything

Current behavior:

- `devlab agent-smoke-test --provider codex`
- If `codex` is configured but unassigned and lacks `[providers.codex.defaults]`, target selection returns zero checks and one skipped provider.
- `AgentSmokeResult.passed` is `all([])`, so the command exits successfully.

This is acceptable for broad `--all-providers` scans, where skipped unassigned providers are warnings. It is weak UX for explicit `--provider`, where the operator requested that specific provider.

Suggested rule:

- Skips are warnings for `--all-providers`.
- Skips for explicit selectors such as `--provider codex` should be nonzero or should raise a clear `ValueError`.

### 3. `--provider --model --effort` still cannot smoke-test an unassigned provider without provider defaults

The CLI accepts:

```bash
devlab agent-smoke-test --provider codex --model gpt-5.5 --effort medium
```

However, `load_agent_configuration()` only resolves provider-default configs when `[providers.<name>.defaults]` exists. If the provider is unassigned and has no provider-local defaults, explicit CLI model/effort values are not enough to form a smoke target.

Two possible designs:

- Strict design: provider-local defaults are mandatory for unassigned provider smoke tests. Then document that `--model` and `--effort` only override existing role/default/provider-default policy.
- More flexible design: allow explicit CLI `--model` and `--effort` to provide a complete temporary smoke policy for an unassigned provider without requiring `[providers.<name>.defaults]`.

The flexible design is more operator-friendly, but slightly increases policy-resolution complexity.

### 4. Provider-default resolution adds global loader complexity

`AgentConfiguration` now carries:

- `providers`
- `configured_providers`
- `configured_provider_configs`
- `provider_names`
- `role_providers`
- `resolved`

The names `configured_providers` and `configured_provider_configs` are ambiguous. They do not mean all configured providers; they mean providers that have provider-local defaults resolved for out-of-role smoke testing.

Suggested simplifications:

- Rename fields to something more precise, such as:
  - `provider_default_providers`
  - `provider_default_configs`
- Or move provider-default target resolution out of general `load_agent_configuration()` and into a smoke-test-specific helper.

### 5. Duplicate provider resolution code in `agent_config.py`

`load_agent_configuration()` now has two similar resolution paths:

- provider-local defaults path for `[providers.<name>.defaults]`;
- role resolution path for `[defaults]` plus `[roles.<role>]`.

Both paths parse the provider table, validate prompt transport, render command, optionally discover version, and construct a `CliAgentProvider`.

Suggested simplification:

- Extract an internal helper that resolves one provider invocation from:
  - provider name;
  - provider table;
  - template values;
  - timeout;
  - diagnostic name prefix.

This would reduce future drift between role-based and provider-default-based resolution.

### 6. CLI option exclusivity can move into argparse

Current CLI validation manually rejects combinations of:

- `--role`
- `--provider`
- `--all-providers`

Suggested simplification:

- Use an argparse mutually exclusive group for selection mode.
- Keep `--model` and `--effort` outside that group as policy overrides.

### 7. `_normalized_role_command()` is heuristic

Deduplication currently normalizes role-specific rendered commands by replacing command args equal to the role name with `{role_name}`.

This supports deduplicating configs that only differ because `{role_name}` was rendered before grouping. But it is heuristic: a literal arg that happens to equal a role name would be normalized too.

Possible simplifications:

- Accept this as a pragmatic edge case and keep the comment.
- Or deduplicate using unresolved provider args plus model/effort/stdin identity instead of rendered command.
- Regardless, printing `agent_result.command` in the report reduces user-facing confusion from this heuristic.

## Recommended Next Steps

1. Change smoke reports to print `agent_result.command`.
2. Decide explicit `--provider` skip semantics:
   - recommended: explicit provider skip is a failure/nonzero outcome.
3. Decide whether CLI `--model` and `--effort` can supply temporary policy for unassigned providers without `[providers.<name>.defaults]`.
4. Rename ambiguous `configured_*` fields or move provider-default resolution out of general config loading.
5. Extract shared provider-invocation resolution helper in `agent_config.py`.
6. Convert smoke selection flags to an argparse mutually exclusive group if it stays clean.

## Current Source Areas

- `src/devlab/agent_smoke.py`: target selection, deduplication, progress events, report formatting.
- `src/devlab/agent_config.py`: role config loading and provider-local default config loading.
- `src/devlab/cli.py`: `agent-smoke-test` CLI flags and progress output.
- `src/devlab/doctor_agent_config.py`: static validation for provider-local defaults.
- `docs/agent-configuration.md`: operator-facing TOML model and smoke-test documentation.
- Tests:
  - `tests/test_agent_smoke.py`
  - `tests/test_agent_config.py`
  - `tests/test_cli.py`
  - `tests/test_doctor.py`
