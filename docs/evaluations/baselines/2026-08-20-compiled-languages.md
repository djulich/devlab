# Compiled-Language Live Evaluation Baseline — 2026-08-20

Scenarios:

- `live-rust-cli-happy-path`
- `live-go-cli-happy-path`
- `live-c-cmake-cli-happy-path`
- `live-cpp-cmake-cli-happy-path`

Rust and C++ were run at DevLab commit `bc8e37b`; Go and C were run at
`e4d63a3`. All four used role-specific local agent configuration: Codex
`gpt-5.5` for architecture, planning, development, integration, and architecture
review; Claude `opus` for task review. The local configuration and provider
credentials remain outside the repository.

## Outcome

All four evaluations passed their strict profile-verification contract. Each
workflow completed in eight sessions with this role sequence:

```text
architect, planner, developer, reviewer, developer, reviewer, integrator, architect
```

Each produced two closed tasks: a profile-bootstrap task under `default` and a
product task assigned to the dedicated language profile. None of the runs had
task rework, findings, review rejections, contract warnings, quality warnings,
or unattributed developer/reviewer sessions. Each target had a clean worktree,
eight session commits, and a `devlab/milestone/M1` tag.

The profile-bootstrap task had `not_configured` developer verification because
the initial `default` profile intentionally had no validation commands. This is
expected. The product tasks inherited their dedicated profile defaults and
recorded passing developer verification. Milestone M1 was `verified` from the
same profile-sourced commands.

## Rust

- Dedicated profile: `rust`, assigned to product task `T0002`
- Developer and milestone commands: `cargo fmt --check`, `cargo test`
- Black-box checks: all 5 passed
- Generated Rust tests: 11 passed across unit and CLI integration suites
- Workflow: 8 sessions, 2 closed tasks, 0 rework or findings
- Git: clean, 8 session commits, M1 tag present

The successful rerun confirmed the fix in `bc8e37b`. An earlier product run had
copied explicit `validation = []` task boilerplate, suppressing the `rust`
profile even though agents ran Cargo manually. The safer template now omits task
validation so profile defaults are durable workflow evidence, and the live
grader requires that evidence.

## Go

- Dedicated profile: `go`, assigned to product task `T0002`
- Developer and milestone commands: `test -z "$(gofmt -l .)"`, `go test ./...`
- Black-box checks: all 5 passed
- Workflow: 8 sessions, 2 closed tasks, 0 rework or findings
- Git: clean, 8 session commits, M1 tag present
- Ignored artifact footprint: none reported

The evaluator independently exercised signed subtraction while the generated Go
test suite covered the command contract. The product task inherited both Go
commands from the dedicated profile, and the same passing profile-sourced
evidence verified milestone M1.

## C/CMake

- Dedicated profile: `c`, assigned to product task `T0002`
- Developer and milestone commands: `cmake --preset dev`, `cmake --build
  --preset dev`, `ctest --preset dev`
- Black-box checks: all 6 passed
- Generated CTest suite: 11 passed
- Workflow: 8 sessions, 2 closed tasks, 0 rework or findings
- Git: clean, 8 session commits, M1 tag present

The evaluator independently exercised signed subtraction. The generated CTest
suite covered invalid command, arity, integer, and overflow boundaries. CMake
`build/` was classified as “other ignored” output: 213,008 bytes with no warning.

## C++/CMake

- Dedicated profile: `cpp`, assigned to product task `T0002`
- Developer and milestone commands: `cmake --preset dev`, `cmake --build
  --preset dev`, `ctest --preset dev`
- Black-box checks: all 6 passed
- Generated CTest suite: 6 passed
- Workflow: 8 sessions, 2 closed tasks, 0 rework or findings
- Git: clean, 8 session commits, M1 tag present

The evaluator also exercised successful signed multiplication plus invalid
command, arity, integer, and overflow boundaries independently of the target's
workflow roles.

## Implications and follow-up

The four runs provide positive end-to-end evidence for dedicated
compiled-language profiles, inherited validation, durable developer/milestone
records, external black-box grading, and operator-owned toolchain prerequisites.
The initial compiled-language profile baseline is complete. Do not add broader
toolchain variants without evidence that they exercise distinct uncovered
behavior.

Rust `target/` and the C/C++ CMake `build/` directories were classified as
“other ignored” artifacts rather than conventional toolchain output. C reported
213,008 bytes, C++ reported 355,629 bytes, and Rust reported about 43.6 MB; none
produced a warning. Go reported no ignored footprint. Treat this as supporting
hygiene evidence, not a correctness failure.

Persistent diagnostics were not copied outside the pytest temporary targets.
Future live runs can set `DEVLAB_EVAL_RESULTS_DIR` when durable raw diagnostics
are useful.
