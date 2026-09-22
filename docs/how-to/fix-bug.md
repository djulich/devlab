# Fix a Bug

Use this procedure to turn a reproducible defect into a planned, reviewed
change. For a repository that has never been planned by DevLab, first follow
[Adopt an existing project](adopt-existing-project.md).

## 1. Establish a clean baseline

Reproduce the bug when practical and record the current test result. Commit or
otherwise resolve unrelated work. DevLab requires a clean Git working tree
before planning and implementation sessions.

## 2. Specify the correction

Add or update a Markdown file under `.devlab/specs/system/`. Include:

- the observable incorrect behavior;
- the expected behavior;
- a minimal reproduction or triggering conditions;
- important compatibility or non-regression constraints; and
- acceptance criteria that can be verified.

Put deployment or operational requirements under
`.devlab/specs/deployment/` when the fix affects them. Specifications are
operator-owned inputs: planning reads them and does not overwrite them.

## 3. Configure the validation path

Make sure `.devlab/config/profiles/*.toml` uses the project's own tests, linting,
build commands, or documented prerequisites. A regression test should be part
of the desired result when it can reliably demonstrate the defect.

Commit the specification and any intentional configuration changes:

```bash
git add .devlab/specs .devlab/config
git commit -m "Specify bug fix"
```

## 4. Plan the fix

If executable configuration changed, review it and run
`devlab trust executable-config` before starting agents.

Reconcile the newly committed specification with the existing plan:

```bash
devlab doctor
devlab plan
```

`plan` is used here deliberately to stop before implementation so you can
inspect the proposed work. If its session limit is reached, follow its summary
and finish planning before proceeding. For routine continuation without this
inspection boundary, use `devlab continue`.

Inspect the generated task acceptance criteria and profile assignment under
`.devlab/tasks/`. Do not manually rewrite generated state merely to bypass a
validation error; use `devlab doctor` to identify the underlying problem.

## 5. Implement and review

```bash
devlab continue --max-sessions 20
```

DevLab runs bounded developer and reviewer sessions and commits valid session
changes. Follow the final summary if more sessions, executable-configuration
approval, research, or an operator clarification is required.

## 6. Verify the outcome

```bash
devlab doctor
devlab status --verbose
devlab diagnostics
```

Run any appropriate project-level acceptance or regression checks that are not
already covered by the selected profile. Review the source changes, generated
workflow records, and Git history before considering the fix complete.
