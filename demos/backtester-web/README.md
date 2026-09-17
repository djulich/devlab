# Backtester Web Specification Demo

This package preserves the web-based evolution of the backtester specification.
It is a substantial target input fixture, not a maintained reference
implementation or a current live-evaluation baseline.

- [`system-spec.md`](system-spec.md) defines the web application behavior and
  architecture constraints.
- [`deployment-spec.md`](deployment-spec.md) defines container and deployment
  requirements.

To use the fixture, copy the files into a disposable target workspace as
`.devlab/specs/system/backtester-web.md` and
`.devlab/specs/deployment/backtester-web.md`, configure an agent provider and
appropriate profiles, commit the inputs, and run `devlab continue`.

