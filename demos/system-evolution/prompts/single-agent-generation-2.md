# Single-Agent Prompt — Generation 2

Update the existing software system so it completely satisfies the current
`specs/system-spec.md` and `specs/deployment-spec.md`.

This repository contains a completed generation 1 implementation and its
migration history. The current generation 2 specifications are complete and
authoritative. Inspect the repository and infer the existing design from durable
files; you have no transcript or conversational memory from the agent that
created generation 1.

Implement all required changes across PostgreSQL migrations, backend API,
frontend behavior, tests, Compose deployment, cross-boundary smoke validation,
and documentation. Preserve existing generation 1 data. Do not reset, replace,
or delete the database volume as an upgrade strategy. Validate both upgrade from
generation 1 and clean installation behavior as fully as the available
operator-installed tools permit.

Work autonomously until the complete generation 2 system is ready. Do not weaken
or rewrite the specifications to match the implementation. Do not install
missing host tools; report any such verification as unverified. Keep credentials
and generated runtime artifacts out of Git. Commit the completed work with clear
commit messages and leave the working tree clean.

You do not have access to an external evaluation grader. Use only the
specifications, repository contents, and project-owned validation to judge
completion.
