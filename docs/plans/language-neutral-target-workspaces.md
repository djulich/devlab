# Language-Neutral Target Workspaces Plan

This plan implements the language-neutral target support item in `docs/todo.md`.
DevLab itself remains a Python CLI/package, but the repositories it operates on
must be able to use Rust, Go, C, C++, or another project-owned toolchain without
receiving Python-specific product guidance.

## Goal

Make language neutrality an exercised product contract rather than only a design
principle.

Key outcomes:

- A newly initialized workspace is not implicitly specified as a Python project.
- Operators can intentionally select useful starter tooling for common languages.
- The orchestrator, prompts, profiles, diagnostics, and workflow state remain
  independent of the target implementation language.
- Rust, Go, C, and C++ workflows have deterministic evaluation coverage.
- Mixed-language repositories use ordinary task profiles and a repository-owned
  integration entry point, without adding language branches to orchestration.
- Missing compilers, package managers, build systems, and analyzers are reported
  as unverified prerequisites; DevLab does not install host tools.

## Existing Foundation

The core model already supports this direction:

- profile lifecycle and validation entries are arbitrary target-owned commands;
- task `validation` metadata can override profile defaults;
- each task resolves to a named profile;
- prompts describe the resolved profile and commands instead of choosing a test
  runner in orchestration code;
- a profile can contain commands spanning more than one toolchain;
- `DEVLAB_PYTHON` belongs to DevLab's handoff submission protocol and does not
  require the target product to contain Python code.

The primary current coupling is the initialized `tooling.md` and `default.toml`,
which prescribe a Python package. Evaluation coverage is also weighted toward
Python targets, so language neutrality has not yet been demonstrated across the
requested compiled toolchains.

## Design Decisions

### Keep Toolchain Policy Out of the Orchestrator

Do not add Rust, Go, C, or C++ conditionals to `orchestrator.py`. Toolchain
selection, setup, build, lint, test, and cleanup commands remain target-owned
configuration expressed through profiles, task validation, and documented
repository entry points.

The same rule applies to future languages: supporting a target language should
normally require a template/example and evaluation, not a new orchestration
branch.

### Use a Neutral Default with Explicit Starter Templates

Change initialization so its default tooling policy is language-neutral. Add an
explicit template selection surface, provisionally:

```text
devlab init --template neutral|python|rust|go|c|cpp
```

`neutral` should be the default. It should instruct the architect and planner to
preserve an existing repository's build conventions and, for a greenfield
project, to make the toolchain an explicit design decision. Its default profile
must not claim validation commands that do not yet exist.

Language templates are starter configuration, not language detection or a
permanent DevLab policy. Each template may provide:

- a concise tooling policy;
- a default profile summary;
- conventional validation commands;
- conditional environment setup only when it is safe and useful;
- relevant generated-artifact guidance.

Do not initially auto-detect a template from files such as `Cargo.toml`,
`go.mod`, or `CMakeLists.txt`. Existing and mixed repositories can contain
several manifests, and silent selection would make initialization surprising.
Detection may later be offered as an advisory suggestion with an explicit
operator choice.

### Preserve Existing Workspace Compatibility

Do not rewrite existing `.devlab/config/tooling.md` or profile files during a
DevLab upgrade. The change affects new initialization and explicit `--force`
behavior only. Keep the current Python starter available as `--template python`
so existing documentation and users have a direct migration path.

Record the selected template in the initialized manifest only if it is useful
for diagnostics; runtime behavior must continue to derive from the actual
profile files, not the historical template name. A template must not become a
new hidden language mode.

### Prefer Repository-Owned Stable Entry Points

Templates may show ecosystem-native commands, but generated projects should
prefer stable workspace-root entry points such as checked-in scripts, Make
targets, CMake presets, Cargo workspace commands, or Go module commands. DevLab
should execute what the target declares rather than reconstruct build-system
knowledge.

Illustrative validation defaults are:

- Rust: `cargo fmt --check`, `cargo clippy ...`, `cargo test --workspace`;
- Go: formatting check, `go vet ./...`, `go test ./...`;
- C/C++: checked-in CMake presets or project-owned `make check` targets.

Exact commands need to be tested and documented per template. In particular,
C and C++ must not assume that every project uses CMake, GCC, Clang, sanitizers,
or one directory layout.

### Treat Missing Host Tools as Prerequisites

DevLab may invoke configured compiler, formatter, analyzer, package-manager, and
build-system commands. It must not install missing host tools. Setup commands may
prepare dependencies through an already-installed target tool when explicitly
configured, subject to the existing executable-configuration trust model.

Diagnostics and future orchestrator-owned validation should distinguish:

- command passed;
- command failed;
- command timed out;
- command could not start because a required tool was unavailable;
- no mechanical validation was configured.

This should reuse the general validation/prerequisite model being developed in
the workflow-contract hardening plan, not introduce language-specific outcome
types.

## Implementation Phases

### Phase 1: Audit and Guard Language-Neutral Boundaries

1. Audit packaged prompts, initialization resources, doctor checks, prompt
   assembly, status/diagnostics, evaluation helpers, and operator documentation
   for assumptions about target languages or repository layouts.
2. Classify each Python reference as either DevLab's own implementation tooling,
   an explicitly Python target template/evaluation, or an unintended reusable
   target assumption.
3. Add focused tests around the generic profile contract using non-Python
   command strings so future changes cannot silently specialize it.
4. Document that `DEVLAB_PYTHON` is a DevLab control-plane interpreter, not a
   target-project language requirement.

### Phase 2: Template-Aware Initialization

1. Define a small template representation owned by `init.py` and packaged init
   resources. Avoid a plugin system or a new domain module unless concrete
   template behavior becomes too large for the owning initialization module.
2. Add the CLI template option and validate unknown template names with a clear
   error.
3. Replace the default generated Python policy/profile with neutral resources.
4. Preserve the current Python resources as the explicit Python template.
5. Add initial Rust, Go, C, and C++ resources. Keep C and C++ guidance flexible
   about build systems and make the starter's chosen convention explicit.
6. Update `format_init_next_steps()`, README, operator guide, and examples.
7. Add initialization tests for every template, default behavior, invalid names,
   `--force`, and existing-file preservation.

### Phase 3: Deterministic Single-Language Evaluations

Add minimal scripted evaluation scenarios in increasing order of variability:

1. Rust Cargo CLI or library;
2. Go module CLI or library;
3. C project using one documented starter build convention;
4. C++ project using one documented starter build convention.

Each scenario should verify more than file presence. Where its toolchain is
available, black-box checks should compile and execute behavior, run tests, and
confirm that planned tasks use an appropriate profile. Tool-dependent scenarios
must skip clearly when the host prerequisite is absent rather than install it or
fail the Python development suite for environmental reasons.

Scripted agents should exercise normal architecture, planning, development,
review, and integration transitions. Add opt-in live-agent variants only after
the deterministic scenario is stable and inexpensive enough to diagnose.

For each ecosystem, evaluate whether agents reliably:

- choose or preserve the intended build system;
- create an adequate `.gitignore`;
- keep generated build/cache artifacts out of Git;
- use profile/task validation rather than relying on globally remembered
  conventions;
- produce executable behavior and tests;
- report unavailable optional tools honestly.

### Phase 4: Mixed-Language Baseline

After at least two single-language compiled scenarios pass reliably, add one
mixed-language evaluation. Prefer a small repository with independently testable
components and one repository-owned integration command rather than a complex
distributed system.

The baseline should demonstrate:

- component tasks select different profiles;
- dependencies order cross-component work correctly;
- each component can run its focused validation;
- an integration profile or integration task runs the cross-component check;
- the integrator sees repository-wide validation evidence;
- no orchestration code branches on language.

One profile per task remains the rule. A cross-toolchain task selects an
aggregate profile whose commands intentionally cover all relevant components.
Only revisit composite-profile metadata if evaluations show repeated duplication
or lifecycle conflicts that cannot be handled by a project-owned aggregate
profile.

### Phase 5: Evidence-Driven Refinement

Collect deterministic and opt-in live outcomes before adding more abstraction.
Potential follow-ups, only when supported by observed failures, include:

- advisory manifest detection during initialization;
- reusable profile inheritance or composition;
- richer prerequisite reporting;
- platform-specific template variants;
- persistent service orchestration for integration validation.

## Test and Validation Strategy

Focused DevLab tests should cover:

- neutral initialization contains no Python target policy;
- every explicit template produces the intended tooling/profile files;
- existing workspace files remain untouched without `--force`;
- profile loading and prompt rendering preserve arbitrary command strings;
- doctor accepts valid non-Python and aggregate profiles;
- missing profile/tool configuration is diagnosed without mutation;
- evaluation skips identify the missing host executable;
- mixed-language tasks resolve their selected profiles independently.

Run the complete DevLab development validation for implementation changes:

```text
make check
```

Toolchain-backed evaluation commands must be separately documented so CI and
operators can distinguish DevLab's own Python test prerequisites from optional
target-language prerequisites.

## Documentation Changes

Update:

- `README.md` to state clearly that DevLab is implemented in Python but target
  repositories are language-independent;
- `docs/operator-guide.md` with template selection and custom profile examples;
- `docs/design.md` with the neutral initialization contract;
- `docs/evaluations.md` with toolchain prerequisites and scenario status;
- initialized `config/README.md` and `config/tooling.md` guidance;
- this plan and `docs/plans/README.md` as phases are completed.

Avoid turning the main operator guide into an exhaustive language-tool manual.
Templates should be small starting points, and target repositories remain the
authority for their build and validation conventions.

## Completion Criteria

The initial language-neutral support effort is complete when:

- `devlab init` defaults to a neutral target configuration;
- explicit Python, Rust, Go, C, and C++ starter templates are documented and
  covered by tests;
- deterministic Rust, Go, C, and C++ scenarios demonstrate normal workflow
  completion when their host tools are available;
- missing toolchains produce skips or actionable prerequisite diagnostics and
  are never installed by DevLab;
- reusable prompts and orchestration contain no target-Python assumptions;
- at least one mixed-language scenario demonstrates component profiles plus a
  repository-owned integration validation path, or mixed-language support is
  explicitly left as the next active phase with recorded single-language
  evidence;
- `make check` passes.

## Non-Goals

- Reimplementing Cargo, Go, Make, CMake, Meson, or compiler discovery in DevLab.
- Installing compilers, SDKs, build systems, package managers, or analyzers.
- Guaranteeing compatibility with every C/C++ build system or platform in the
  first release.
- Adding language-specific workflow roles or orchestration states.
- Requiring mixed-language profile composition before an aggregate profile has
  proved insufficient.
- Removing Python as DevLab's own implementation and installation language.
