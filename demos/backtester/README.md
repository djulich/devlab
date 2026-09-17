# Backtester Specification Demo

This package preserves a substantial desktop backtesting-system specification
used to exercise DevLab against a more complex target than the introductory
workflow. It is an input fixture, not a maintained reference implementation or
an assertion that every current DevLab feature has been evaluated against it.

- [`system-spec.md`](system-spec.md) defines the application behavior and
  architecture constraints.
- [`deployment-spec.md`](deployment-spec.md) defines Linux RPM and systemd
  packaging requirements.

To use the fixture, copy the files into a disposable target workspace as
`.devlab/specs/system/backtester.md` and
`.devlab/specs/deployment/backtester.md`, configure an agent provider and
appropriate profiles, commit the inputs, and run `devlab continue`.

