# Project Identity

DevLab is a reusable CLI and Python package for running an auditable, file-backed, role-based agentic software development workflow inside a target repository.

DevLab operates like a project-local development harness: the package provides reusable orchestration logic and worker prompt resources, while the target repository stores product-specific specifications, configuration, plans, tasks, milestones, findings, logs, and handoffs under `.devlab/`.

For the canonical design model, workflow, state layout, and current implementation details, see [`devlab-design.md`](devlab-design.md).
