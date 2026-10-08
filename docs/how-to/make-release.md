# Make a release

Commands use `0.2.0` as an example, with `0.1.2` as the previous release. Substitute your release and previous-release versions throughout. Run commands from the repository root in the same shell.

## 1. Confirm the release scope and version.

Review the changes between the last release and the current state:

```bash
git log --oneline v0.1.2..HEAD
git diff --stat v0.1.2..HEAD
```

Choose the next version using the [version-selection rules](../release-policy.md#choosing-the-next-version).

## 2. Update the version.

Change `[project].version` in `pyproject.toml` to `0.2.0`, then refresh the lockfile:

```bash
uv lock
```

Inspect the lockfile diff; avoid unrelated dependency updates.

## 3. Prepare the release notes.

Summarize notable changes and any upgrade or recovery instructions. Save the notes to `/tmp/devlab-0.2.0-notes.md` for the annotated tag created in step 6.

## 4. Run development validation and assess evaluation needs.

```bash
make check
```

_This runs ruff, ty, pytest, and the normal scripted workflow evaluations._

If the changes warrant additional evaluation, select and run the relevant scenarios from the [evaluation guide](../evaluations/README.md), including live-agent baselines where needed.

## 5. Run package verification.

```bash
make release-check
```

_Checks distribution contents and metadata, then installs the wheel in a clean environment and verifies the CLI._

## 6. Commit new version and create an annotated tag.

Review the changes and stage the version and lockfile:

```bash
git add pyproject.toml uv.lock
```

Explicitly stage any other intended release changes, then commit:

```bash
git commit -m "chore: prepare release 0.2.0"
```

Check that the worktree is clean:

```bash
git status --short
```

Expect no output. Resolve any remaining changes before creating the tag:

```bash
git tag -a v0.2.0 -F /tmp/devlab-0.2.0-notes.md
git rev-parse HEAD
git rev-parse 'v0.2.0^{commit}'
```

The last two hashes must match.

## 7. Verify installation from the exact commit before sharing it.

Use a temporary environment outside the editable checkout:

```bash
release_verify=$(mktemp -d /tmp/devlab-0.2.0-verify.XXXXXX)
release_commit=$(git rev-parse HEAD)

uv venv --python 3.12 "$release_verify/commit"
uv pip install --python "$release_verify/commit/bin/python" \
   "git+file://$(pwd)@$release_commit"

"$release_verify/commit/bin/devlab" --version
"$release_verify/commit/bin/devlab" --help
```

Expect `devlab 0.2.0`.

_Temporary environments leave your installed DevLab unchanged._

## 8. Push the release commit, then the specific tag.

```bash
git push origin main
git push origin v0.2.0
```

The tag push triggers the GitHub `Prepare release` workflow. Once pushed, do not repoint or replace the release tag. Release corrections under a new version and tag.

_The workflow automatically checks tag/version agreement, reruns validation, builds the publication artifacts once, verifies them, and generates checksums. It then creates a draft GitHub Release and requests TestPyPI approval._

## 9. Approve and inspect TestPyPI before production.

On [GitHub](https://github.com/djulich/devlab), open **Actions → Prepare release → the run for your tag → Review deployments**.
Approve the `testpypi` deployment with **Approve and deploy**, then wait for the upload job to succeed.

On [TestPyPI](https://test.pypi.org/project/devlab/), select the new version and inspect its short description, README rendering, links, wheel, source distribution, and provenance.

Follow the **Release Notes** project link to [GitHub's release list](https://github.com/djulich/devlab/releases) and select the matching draft. Review its notes and assets. For versions before `1.0.0`, choose **Edit release → Release label → Pre-release → Save draft**.

Test both installation sources separately:

```bash
uv venv --python 3.12 "$release_verify/testpypi"
uv pip install --python "$release_verify/testpypi/bin/python" \
   --default-index https://test.pypi.org/simple/ "devlab==0.2.0"
"$release_verify/testpypi/bin/devlab" --version
"$release_verify/testpypi/bin/devlab" --help
```

```bash
uv venv --python 3.12 "$release_verify/tag"
uv pip install --python "$release_verify/tag/bin/python" \
   "git+https://github.com/djulich/devlab.git@v0.2.0"
"$release_verify/tag/bin/devlab" --version
"$release_verify/tag/bin/devlab" --help
```

Both must report `devlab 0.2.0` and display command help.

_The GitHub pre-release label does not make `0.2.0` a prerelease version to Python package installers._

## 10. Approve production publication.

Only after candidate inspection succeeds, approve the `pypi` deployment in the workflow run's **Review deployments** dialog. Wait for the upload job to succeed.

_Production consumes the same verified distributions uploaded to TestPyPI. It does not rebuild them. SHA256SUMS stays a GitHub Release asset._

## 11. Verify production, then publish the GitHub Release.

On [PyPI](https://pypi.org/project/devlab/), select the new version and inspect its short description, README rendering, links, wheel, source distribution, and provenance.

Open **Release files → Details** for each distribution. Compare its **SHA256** with the checksum listed for the matching filename inside the GitHub Release Asset's `SHA256SUMS` file.

Verify that the production installation reports `devlab 0.2.0` and displays command help:

```bash
uv venv --python 3.12 "$release_verify/pypi"
uv pip install --python "$release_verify/pypi/bin/python" \
   --default-index https://pypi.org/simple/ "devlab==0.2.0"
"$release_verify/pypi/bin/devlab" --version
"$release_verify/pypi/bin/devlab" --help
```

Then publish the reviewed GitHub Release (**Edit release → Publish release**), keeping its pre-release designation for versions before `1.0.0`.

_Publishing the GitHub Release makes its notes and assets public; the package was already published by the PyPI deployment._

If publication fails, inspect whether any files were uploaded before retrying. Corrections that change published artifacts require a new version and tag.
