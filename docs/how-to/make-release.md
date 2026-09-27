# Make a release

This how-to document describes the steps required to create a release. The example illustrates the process for the hypothetical release v0.1.3.

## 1. Confirm the release scope and version.

Review:

git log --oneline v0.1.2..HEAD
git diff --stat v0.1.2..HEAD

Describe this as a documentation and package-metadata release. It introduces no runtime or durable-
format changes, so these changes require no workspace migration.

One policy ambiguity: it calls patch releases “bugfix-only” without explicitly mentioning
documentation or metadata corrections. I recommend clarifying that those corrections also qualify for
patch releases. There is no reason to use 0.2.0 for the current changes.

  2. Check publishing prerequisites and push access.

     You need working Git, Python 3.12+, uv, GitHub access, and permission to approve both publishing
     environments.

     The existing trusted publishers should remain configured for:
      - Repository: djulich/devlab
      - Workflow: release.yml
      - Environments: testpypi and pypi

     No PyPI API token is required. I verified GitHub environment settings, but not the private trusted-
     publisher settings inside the index accounts.

     A local issue to resolve: my SSH remote query failed with “Bad owner or permissions” for /etc/ssh/
     ssh_config.d/20-systemd-ssh-proxy.conf. GitHub API access worked. Confirm Git push access before
     preparing the tag.

  3. Update the version and installation examples.

     Change [project].version in pyproject.toml to 0.1.3, then refresh the lockfile:

     UV_CACHE_DIR=/tmp/uv-cache uv lock

     Inspect the lockfile diff; avoid unrelated dependency updates.

     Update the current pinned installation examples in:
      - README.md: devlab==0.1.3 and @v0.1.3
      - docs/tutorial.md: devlab==0.1.3

     Leave historical release evidence and baseline versions unchanged. Do not bump workflow schema
     versions.

  4. Prepare the release notes.

     The GitHub Release is the canonical release note; no separate changelog is required.

     Suggested scope:

     > DevLab 0.1.3 improves the project introduction, architectural explanation, and operator recovery
     > documentation, and updates the package summary displayed on PyPI.
     >
     > Runtime behavior and durable workspace formats are unchanged from 0.1.2. These changes require no
     > workspace migration. DevLab remains pre-1.0 with provisional compatibility.

     Add actual validation results after running them. If no new live-agent evaluation is performed, say
     so.

     Save the full notes in a temporary file for an annotated tag, matching your preferred release
     practice.

  5. Run development validation and assess evaluation needs.

     UV_CACHE_DIR=/tmp/uv-cache make check

     This runs Ruff, ty, pytest, and the normal scripted workflow evaluations.

     For this documentation-only release, I would not require another live-agent baseline. Record that
     decision and its rationale. Optional deployment/toolchain checks should be driven by release risk;
     missing prerequisites must remain reported as skipped or unverified.

     The remaining 1.0 compatibility exercises in issue #6 are separate from publishing this provisional
     patch release.

  6. Run package verification.

     UV_CACHE_DIR=/tmp/uv-cache make release-check

     This checks the wheel and source distribution, metadata, version agreement, license, packaged
     resources, distribution contents, README link form, strict Twine validation, clean wheel installation,
     and CLI version/help.

     Manually inspect the new short description too. Automated rendering and metadata checks do not replace
     checking how the description looks on the index or whether its links work.

  7. Commit preparation and create an annotated tag.

     Review and commit the version, lockfile, example updates, and any policy clarification:

     git add pyproject.toml uv.lock README.md docs/tutorial.md
     git commit -m "chore: prepare release 0.1.3"

     Include docs/release-policy.md if you clarified patch-release scope.

     With a clean worktree, create the tag using your prepared notes:

     git tag -a v0.1.3 -F /tmp/devlab-0.1.3-notes.md
     git status --short
     git rev-parse HEAD
     git rev-parse 'v0.1.3^{commit}'

     The last two hashes must match. Tag signing is optional under the current policy.

  8. Verify installation from the exact commit before sharing it.

     Use a temporary environment outside the editable checkout:

     release_verify=$(mktemp -d /tmp/devlab-0.1.3-verify.XXXXXX)
     release_commit=$(git rev-parse HEAD)

     uv venv --python 3.12 "$release_verify/commit"
     uv pip install --python "$release_verify/commit/bin/python" \
       "git+file:///home/dirk/repos/devlab@$release_commit"

     "$release_verify/commit/bin/devlab" --version
     "$release_verify/commit/bin/devlab" --help

     Expect devlab 0.1.3.

     These isolated virtual environments satisfy the policy’s intent without replacing your normal uv tool
     installation.

  9. Push the release commit, then the specific tag.

     git push origin main
     git push origin v0.1.3

     The tag push triggers Prepare release. Never move a shared release tag.

     The workflow automatically checks tag/version agreement, reruns validation, builds the publication
     artifacts once, verifies them, and generates checksums. It then creates a draft GitHub Release and
     requests TestPyPI approval.

  10. Approve and inspect TestPyPI before production.

     In the workflow’s Review deployments dialog, approve testpypi.

     Inspect the TestPyPI version, short description, README rendering, links, wheel, source distribution,
     and provenance. Review the draft GitHub Release’s notes and assets, and mark it as a pre-release.

     Test both installation sources separately:

     uv venv --python 3.12 "$release_verify/testpypi"
     uv pip install --python "$release_verify/testpypi/bin/python" \
       --default-index https://test.pypi.org/simple/ "devlab==0.1.3"
     "$release_verify/testpypi/bin/devlab" --version
     "$release_verify/testpypi/bin/devlab" --help

     uv venv --python 3.12 "$release_verify/tag"
     uv pip install --python "$release_verify/tag/bin/python" \
       "git+https://github.com/djulich/devlab.git@v0.1.3"
     "$release_verify/tag/bin/devlab" --version
     "$release_verify/tag/bin/devlab" --help

     Both must report 0.1.3. The GitHub pre-release label does not make 0.1.3 a prerelease version to
     Python package installers.

  11. Approve production publication.

     Only after candidate inspection succeeds, approve pypi in Review deployments.

     Production consumes the same verified distributions uploaded to TestPyPI. It does not rebuild them.
     SHA256SUMS stays a GitHub Release asset.

  12. Verify production, then publish the GitHub Release.

     Check the production version, description, links, files, and publisher provenance. Compare both
     distribution SHA-256 hashes against the workflow-generated SHA256SUMS.

     uv venv --python 3.12 "$release_verify/pypi"
     uv pip install --python "$release_verify/pypi/bin/python" \
       --default-index https://pypi.org/simple/ "devlab==0.1.3"
     "$release_verify/pypi/bin/devlab" --version
     "$release_verify/pypi/bin/devlab" --help

     Then publish the reviewed GitHub Release, keeping its pre-release designation.

     Retain the workflow URL, validation results, installation checks, hash comparison, and evaluation
     limitations. Do not infer increased maturity from successful packaging alone.

     If publication fails, inspect whether any files were uploaded before retrying. Corrections that change
     published artifacts require a new version and tag.

  Alignment verdict: the policy and workflow agree on the release order, approval gates, immutable tags,
  shared artifacts, and final verification. The two documentation improvements worth making are explicitly
  allowing documentation/metadata patch releases and making the smoke-test isolation concrete.

