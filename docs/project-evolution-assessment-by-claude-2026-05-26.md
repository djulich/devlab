# Project evolution assessment: 2026-05-26

Assessment of DevLab project progress since the reviewer safe-default work (ADR 0007), covering changes made outside the current session. Identifies actual weaknesses and proposes improvements.

## What changed

Three axes of progress:

1. **Deployment domain support implemented** (todo item 11). Task domains (`task_tracker.py`, `domain` field with `general`/`deployment` values), domain prompt overlays (`prompts.py`, `resources/prompts/domains/deployment/*.md`), deployment spec detection, and a complete deployable web API scripted evaluation. Architectural approach: prompt overlays, no orchestrator branching.

2. **Quality metrics and workflow diagnostics.** New `workflow_diagnostics.py` module (583 lines) provides task-cycle attribution, rework detection, integrator finding tracking, profile metrics, artifact hygiene, and a quality summary with warnings. Used by both the evaluation harness and normal `devlab run` via CLI.

3. **Three new evaluation scenarios**: stateful web API, static frontend, and deployable web API — each with scripted and opt-in live variants. Evaluation harness refactored to extract `checks.py` and share diagnostics computation with `workflow_diagnostics.py`. Live baselines informed iterative refinements to reviewer prompts, API contract specs, and quality thresholds.

Tests: 275 pass, 4 skipped, lint clean.

## Weakness 1: untyped dict returns in `workflow_diagnostics.py`

The module uses `dict[str, object]` for nearly all return types (`task_metrics`, `artifact_hygiene`, `profiles`, `quality`, etc.), requiring `cast()` and `isinstance()` checks at every consumption point. Callers can silently access wrong keys, get runtime `KeyError`s, or pass malformed dicts without static-analysis warnings. The module already has well-defined shapes (the `WorkflowDiagnostics` dataclass fields mirror them), but the individual collector functions return untyped dicts.

**Recommendation**: Define frozen dataclasses for each metric group (e.g. `TaskMetrics`, `ArtifactHygiene`, `ProfileMetrics`, `QualitySummary`) and return those instead. Incremental — convert one collector at a time, update callers, drop casts. The JSON serialization path (`as_dict()` / `to_json()`) already uses `dataclasses.asdict()`, so adding nested dataclasses is transparent.

**Priority**: medium — working now but will become painful as consumers multiply.

## Weakness 2: evaluation harness re-exports obscure module boundaries

`harness.py` re-exports everything from `workflow_diagnostics` and `checks` via `__all__`, so test files import functions like `derive_role_sequence`, `quality_summary`, `collect_artifact_hygiene` from `harness` rather than from their owning modules. The harness acts as an unnecessary facade for unrelated concerns.

**Recommendation**: Have tests import directly from `workflow_diagnostics` and `checks`. Remove re-exports from `harness.py`. The harness should own evaluation orchestration only.

**Priority**: low — cosmetic, but aligns with AGENTS.md module boundary guidance.

## Weakness 3: fragile placeholder detection in `_deployment_spec_has_requirements()`

`prompts.py:103-124` checks for substantive deployment specs by matching two specific placeholder sentences. Any change to init template wording silently breaks detection, and there's no test or cross-reference tying template text to detection strings. Third-party target projects wouldn't know about these magic phrases.

**Recommendation**: Use a simpler heuristic (e.g. non-whitespace character count after stripping the heading) or add a sentinel comment like `<!-- placeholder -->` to the init template. Either way, add a test that modifies the init template and verifies detection still works.

**Priority**: medium — will break silently the next time the template is edited.

## Weakness 4: `scripted_agents.py` growing toward split threshold

829 lines with 5 agent classes containing substantial per-scenario logic. Todo item 10 already acknowledges this: "Consider splitting large scripted evaluation agents by scenario family."

**Recommendation**: Next scenario addition should create `scripted_agents/<scenario>.py` files.

**Priority**: low — still readable.

## Weakness 5: reviewer effectiveness is prompt-tuned, not structurally solved

Quality metrics plan notes "reviewer missed an API contract mismatch that integrator later found" — response was to strengthen reviewer instructions. This is a prompt-tuning approach to a structural problem: the reviewer has no mechanism to actually verify API contracts beyond reading code. Safe-default work (ADR 0007) helps when signals disagree but can't help when the reviewer confidently approves wrong code.

**Recommendation**: Not a code change — a design observation. Real mitigation is profile-driven validation commands the reviewer can run (already on roadmap in todo item 11). The deployable web API live eval showed this works for deployment tasks (reviewer built and smoke-tested the container). Extending to API contract verification is the natural next step.

**Priority**: medium — requires design decision, not just implementation.

## Weakness 6: session context logging in orchestrator mixes concerns

`orchestrator.py:389-454` has `_session_start_context` and `_session_finish_context` building formatted log strings with snapshot queries. These are reporting functions, not workflow logic, adding ~65 lines of role-specific formatting to a module that should own "workflow loop, session lifecycle, handoff processing, error recovery."

**Recommendation**: Move to `workflow_diagnostics.py` or a small internal module.

**Priority**: low — won't cause bugs, but `orchestrator.py` is 745 lines and todo item 10 flags this growth risk.

## What's working well

- Domain overlay system is clean and extensible — adding a domain requires only resource files, no orchestrator changes.
- Quality metrics shared between evaluations and normal operation is smart architecture.
- Evaluation scenario progression (calculator → HTTP API → stateful API → frontend → deployment) is well-paced — each adds one dimension.
- Live eval findings systematically captured and fed back into specs, prompts, and diagnostics — a real feedback loop.
