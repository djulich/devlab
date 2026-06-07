# Domain: Deployment / Reviewer

- Verify that claimed deployment artifacts and project-owned commands exist.
- Run target-owned artifact-generation and verification commands when practical and safe in the configured environment.
- Reject claimed deployment support that is not generatable, testable, or explicitly scoped as documentation-only/future work.
- Check that local or disposable deployments define teardown behavior.
- Check that secrets and environment-specific credentials are not committed.
- Check `.gitignore` coverage for generated packages, images, caches, and local runtime files.
- If a required host deployment tool is missing, do not install it; treat the related deployment claim as unverified unless it is explicitly documented as a user/CI prerequisite.
- Ensure documentation tells users which tools and configuration are required after DevLab finishes.
