# Defer structured deployment validation metadata

DevLab will continue to model deployment verification through task/profile validation commands and target-owned project commands rather than adding deployment-specific structured validation metadata now.

The current evidence is sufficient for the initial deployment scope: deterministic deployment evaluations and the first live deployment baseline produced discoverable project-owned verification commands, deployment-domain task attribution, profile usage diagnostics, and clean workflow history without deployment-specific orchestrator branches. Missing host tools remain user/CI prerequisites under ADR 0008.

Adding first-class deployment validation metadata too early would duplicate task `validation`, profile default validation, Make/script entry points, and documentation. It would also risk pushing deployment-specific policy into the orchestrator, contrary to the role/domain boundary: orchestrator decides workflow, providers invoke agents, trackers store state, and target projects own verification commands.

Revisit this decision only if additional live baselines show repeated failures that cannot be fixed with prompt guidance and diagnostics, such as agents failing to create discoverable project-owned commands, reviewers approving unverified deployment claims without clear missing-tool evidence, or profile validation commands becoming too ambiguous for users/CI to operate.
