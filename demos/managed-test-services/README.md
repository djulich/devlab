# Managed PostgreSQL test service

This example configures a workspace-owned database in an initialized disposable
DevLab target. See the [runtime reference](../../docs/runtime-prerequisites.md)
for the service contract. Keep this database separate from any external grader's
resources.

Prerequisites: Python 3, a usable Docker daemon, and a locally available
`postgres:16` image. The operator supplies these; the example does not install
Docker or pull an image.

1. Copy `postgres.py` to the target's `scripts/test-postgres.py` and
   `test-services.toml` to `.devlab/config/test-services.toml`.
2. Add this reference to each profile that needs the database:

   ```toml
   [[test_services]]
   id = "postgres"
   required_for = ["session", "setup", "validation"]
   ```

3. In an existing target, run `devlab test-service init` and commit the resulting
   `.devlab/.gitignore` along with the scripts/configuration.
4. Review and authorize `devlab trust executable-config`, then run
   `devlab continue`. Configure tests to read `TEST_DATABASE_URL`.
5. Inspect last observed state with `devlab test-service status`.
6. Remove the instance with `devlab test-service cleanup postgres`. If the saved
   definition needs separate authorization, first inspect it with `--show`, then
   trust it with `--trust` or supply the displayed `--require-exec-config-digest`.

The container binds to a random loopback port, has a generated password, and is
identified by DevLab's random instance ID and ownership labels. Repeated setup
preserves its data. Cleanup removes that container and its anonymous volumes,
not other Docker resources. Tests may create disposable databases inside it;
profile session teardown must leave the managed server running.

The container persists until explicit cleanup. Connection files and command
logs live in the target's ignored `.devlab/local/test-services/` directory.
A moved/copied workspace cannot automatically claim the original instance.
The target-owned script implements ownership checks; DevLab authorization does
not sandbox arbitrary scripts or verify their transitive behavior.

Optional integration test from the DevLab checkout:

```sh
DEVLAB_TEST_DOCKER=1 UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q tests/test_test_services.py -k docker
```

The test skips if the daemon or local image is unavailable. It creates a fresh
owned container and removes it in a `finally` block.
