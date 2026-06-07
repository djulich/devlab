# Domain: Deployment / Developer

- Implement the project-owned deployment artifacts, commands, scripts, and documentation required by the task.
- Make supported artifact-generation and verification commands runnable from the workspace root where practical, using target-owned commands or scripts.
- Add or update smoke tests for local, disposable, or staging deployment environments when required.
- Define teardown commands for local or disposable deployments.
- Maintain `.gitignore` for generated images, packages, caches, local environment files, and other non-product artifacts.
- If a required host deployment tool is missing, do not install it; document it as an unverified user/CI prerequisite in the handoff and project docs.
- Do not commit secrets or environment-specific credentials; provide examples/templates instead.
