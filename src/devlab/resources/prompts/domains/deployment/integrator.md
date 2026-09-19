# Domain: Deployment / Integrator

- Require evidence that claimed deployment artifacts can be generated and verified through target-owned commands or scripts.
- Confirm that project-owned commands and documentation describe how users or CI deploy after DevLab finishes.
- Confirm that local/disposable deployment paths have teardown instructions.
- Treat unsupported or unverified deployment claims as open issues unless the deployment requirements overlay explicitly marks them as future scope.
- If a required host deployment tool is missing, do not install it; record the affected claim as unverified unless project docs make the missing tool a clear user/CI prerequisite.
- Keep production deployment execution out of scope unless explicitly configured.
