# Domain: Deployment / Planner

- Assign `domain = "deployment"` to tasks whose primary acceptance criteria concern packaging, deployment artifacts, runtime environment commands, smoke tests, teardown, or deployment documentation.
- Plan project-owned commands or scripts for generating deployment artifacts and verifying them.
- Include acceptance criteria that prove claimed deployment support is generatable and testable.
- Include teardown expectations for local, disposable, or staging environments.
- Do not claim production deployment execution unless the deployment specification explicitly configures it.
