# Defer structured deployment validation metadata

DevLab will not add deployment-specific validation metadata yet. Deployment verification remains expressed through target-owned commands, task `validation`, profile defaults, acceptance criteria, and docs.

Current scripted and live deployment baselines produced discoverable verification commands, deployment-domain task attribution, profile diagnostics, and clean workflow history without deployment-specific orchestrator branches. Missing host tools remain user/CI prerequisites under ADR 0008.

First-class metadata would currently duplicate existing command sources and risk moving deployment policy into the orchestrator. Revisit only if live baselines show repeated failures: missing discoverable commands, reviewers approving unverified deployment claims, unclear missing-tool evidence, or profile validation becoming too ambiguous for users/CI.
