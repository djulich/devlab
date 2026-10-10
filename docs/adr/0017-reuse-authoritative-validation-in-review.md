# ADR 0017: Reuse Authoritative Validation in Review

## Status

Accepted. Amends ADR 0016's requirement for independent reviewer execution of
all configured commands.

## Context

Independent review is essential, but running the same expensive suite immediately
after an orchestrator-observed pass does not necessarily add independent scrutiny.
Reviewers should spend that time checking acceptance criteria, test adequacy and
uncovered failure modes. A recorded HEAD alone cannot justify reuse: validation
runs against a working tree that may contain uncommitted implementation changes.

## Decision

The orchestrator may supply a reviewer with the latest complete passing task
validation record when its commands, resolved profile/validation contract,
versionable workspace content and inherited/managed command environment match.
Records identify the actual file content and modes before and after execution;
changed inputs during validation disable reuse. Normal bookkeeping and commits
of identical tested content do not invalidate evidence. Old, malformed, failed,
partial or mismatched records cannot enable reuse. Missing logs and unsupported
inputs (including symlinks and submodules) also disable reuse conservatively.

Reviewers inspect the supplied evidence and independently review behavior and
test adequacy. They run focused checks for uncovered risks, rather than repeat
the configured suite solely for approval. Without supplied matching evidence,
they retain the existing obligation to execute configured checks independently.
Handoffs distinguish reused observations from checks the reviewer actually ran.

This is reuse of a recorded observation, not certification of the current
external environment. Ignored dependencies, installed tools, external services
and physical devices are not identified by the workspace digest. Reviewers must
rerun affected checks when those conditions or environment setup can invalidate
the observation. Matching environment variables and the DevLab interpreter do
not establish external service freshness. No source-only validation cache or
partial-suite resume is introduced.

Before accepting approval that used supplied evidence, the orchestrator checks
its applicability again. A change to identified inputs requires a fresh full
configured run before closure. Failure returns the task to development; missing
tools or infrastructure errors leave it awaiting review and stop progression.
Rejected reviews do not incur an extra suite merely to record the rejection.
Milestone validation and failed-validation retries retain their separate fresh
runs and existing policies.

## Consequences

Validation provenance and progress reporting are reusable mechanics. Deciding
when software review can use that evidence, preserving reviewer independence,
and gating task closure remain software-workflow policy. No generic workflow
interface or new configuration is introduced.

Evidence matching is intentionally conservative and can cause a redundant run
when an unrelated versionable file or environment variable changes. It does not
attempt dependency analysis or certify arbitrary shell-command inputs. Future
optimization must preserve these distinctions rather than broaden cache claims.
