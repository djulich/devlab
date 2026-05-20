# Git-based evaluation hygiene

## Goal

Make workflow-evaluation artifact hygiene classify target files according to Git repository semantics instead of hardcoded assumptions about generated or ephemeral paths.

## Plan

### 1. Git is mandatory for evaluation hygiene

Workflow evaluations require `git` on `PATH`. There is no fallback implementation of `.gitignore` semantics.

If Git is unavailable, the evaluation harness should fail with a clear error.

### 2. Initialize Git repos only when needed

In evaluation target setup:

```text
if root/.git does not exist:
    git init
    git config user.email devlab-eval@example.invalid
    git config user.name "DevLab Eval"
    git add .
    git commit -m "Initial evaluation workspace"
```

If `.git/` already exists, do not reinitialize or create a baseline commit. This keeps future existing-repository scenarios safe.

### 3. Hygiene classification has only three classes

Do not use hardcoded ephemeral presets.

The classes are:

1. **DevLab files**
   - raw filesystem files under `.devlab/`
   - workflow/operational overhead

2. **Product/Git-relevant files**
   - files from:
     ```bash
     git -C <root> ls-files --cached --others --exclude-standard -z
     ```
   - excluding `.devlab/`

3. **Ignored files**
   - files from:
     ```bash
     git -C <root> ls-files --others --ignored --exclude-standard -z
     ```
   - excluding `.devlab/`

Diagnostics should expose:

```json
{
  "product_file_count": 5,
  "product_total_bytes": 1234,
  "ignored_file_count": 649,
  "ignored_total_bytes": 63000000,
  "devlab_file_count": 74,
  "devlab_total_bytes": 147570
}
```

Legacy compatibility keys remain:

```json
"file_count" = product_file_count
"total_bytes" = product_total_bytes
"flagged_paths" = []
```

### 4. Developer prompt guidance

Update the developer prompt with direct repository-hygiene guidance:

```md
When adding tooling/profile-specific generated artifacts, maintain `.gitignore`.

Ensure local environment directories, caches, build outputs, bytecode, and similar generated files are ignored.
```

Do not add a separate profile-driven `.gitignore` mechanism now.

### 5. Tests

Add focused tests around Git classes, not ephemeral presets.

#### A. Ignored files do not count as product artifacts

Setup:

- Git repo
- root `.gitignore` ignores `.venv/`, `.pytest_cache/`, `__pycache__/`
- create:
  - `.gitignore`
  - `calculator.py`
  - `tests/test_calculator.py`
  - `.venv/...`
  - `.pytest_cache/...`
  - `__pycache__/...`
  - `.devlab/tasks/T0001.md`

Assert:

```python
product_file_count == 3  # .gitignore, calculator.py, tests/test_calculator.py
ignored_file_count == 3
devlab_file_count == 1
flagged_paths == []
```

#### B. Unignored files count as product artifacts

No special treatment for `.venv` or caches. If `.venv/file.py` is not ignored, it is simply Git-relevant and counted as product.

Assert:

```python
product_file_count includes ".venv/..."
ignored_file_count == 0
flagged_paths == []
```

#### C. Evaluation init creates Git repo only if absent

- fresh temporary target gets `.git/` and an initial commit
- preexisting Git repo is not reinitialized

### 6. Documentation

Update `docs/evaluations.md`:

- Git is required for workflow evaluations.
- Product artifact metrics use Git-relevant files.
- Ignored files are counted separately.
- `.devlab/` is counted separately as workflow overhead.
- Hygiene evaluation does not guess which ignored files are ephemeral; target/tooling conventions decide via `.gitignore`.

## Net effect

DevLab does not decide what is ephemeral. The target repo does, via Git ignore rules. DevLab only reports the consequences.
