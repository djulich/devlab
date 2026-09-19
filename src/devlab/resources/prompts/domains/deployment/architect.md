# Domain: Deployment / Architect

- Identify deployment targets separately from deployment environments.
- Capture packaging/runtime choices in the design plan: RPM/systemd, container runtime, Compose, Kubernetes manifests, or other explicitly requested targets.
- Define what deployment verification must prove for each claimed target.
- Call out required local tools, disposable/staging infrastructure, and teardown expectations.
- Keep production deployment execution out of scope unless the deployment requirements overlay explicitly configures it.
