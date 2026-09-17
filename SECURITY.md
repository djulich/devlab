# Security Policy

## Reporting a Vulnerability

Please report suspected vulnerabilities through GitHub's private vulnerability
reporting for this repository. Open the repository's **Security** tab, choose
**Report a vulnerability**, and create a private report. Do not open a public
issue for an undisclosed vulnerability.

Include the affected DevLab version or commit, reproduction steps, expected and
observed behavior, potential impact, and any suggested mitigation. Avoid
including credentials, private target-repository content, or other unnecessary
sensitive data.

The maintainers will assess reports on a best-effort basis and coordinate
disclosure and remediation through the private report. DevLab is currently
pre-1.0; the latest commit on `main` and the latest tagged release are the
supported versions unless a report identifies a reason to issue a fix for an
older release.

## Security Boundary

DevLab orchestrates external agent CLIs and executes commands declared by a
target repository. It does not provide its own operating-system sandbox.
Provider sandboxing and approval behavior are controlled by the target's
`.devlab/config/agents.toml`; profiles may also declare lifecycle, prerequisite,
validation, test-service, and deployment commands.

Treat target repositories and their executable configuration as code. Review
them before granting trust or running a mutating workflow command. DevLab's
executable-configuration fingerprint detects relevant changes, but approving a
fingerprint does not make the underlying commands safe. See the
[trust and safety warning](README.md#trust-and-safety-warning) for the operator
model and current limitations.
