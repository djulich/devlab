# Evaluation Baselines

This directory contains dated evidence from representative live evaluations.
Baselines support documented confidence claims; they are not active plans or a
substitute for automated tests. Commands and model/provider names describe the
recorded run; use the [evaluation guide](../README.md) for current instructions.
A historical failure remains part of that run even when later code fixes it.
These records do not establish the installed-candidate compatibility freeze in
the [release policy](../../release-policy.md#10-compatibility-freeze).

- [2026-06-06 deployment baseline](2026-06-06-deployment.md)
- [2026-06-24 stateful web API baseline](2026-06-24-stateful-web-api.md)
- [2026-08-20 compiled-language baseline](2026-08-20-compiled-languages.md)
- [2026-09-17 first-workflow demonstration baseline](2026-09-17-first-workflow.md)
- [2026-09-20 representative workflow baseline](2026-09-20-representative-workflows.md)

Add a baseline only when it records materially new provider, toolchain, workflow,
or deployment evidence. Routine reruns belong in CI artifacts or an external
results system rather than permanent documentation.
