# React/Vite Browser Live Evaluation Plan

Status: implemented.

## First live outcome and calibration — 2026-08-20

The first retained live target completed the DevLab workflow in eight sessions,
closed both tasks, integrated M1, and passed its configured `make test`
verification. The independent browser grader then failed. The generated React
app preferred `VITE_API_BASE_URL=http://127.0.0.1:8765`, but the generated Python
API supplied neither CORS response headers nor preflight handling. Its Vite proxy
worked only for the separately tested default API port 8000, so component tests,
the frontend build, and the default-port proxy smoke test did not prove the
arbitrary-port browser/API claim.

This result tightened the implemented scenario contract:

- browser code uses same-origin relative routes;
- Vite obtains its proxy target from `API_BASE_URL`, with port 8000 only as the
  local default;
- the independent grader selects a non-default API port and no longer injects a
  browser-visible cross-origin base URL;
- the target must provide `make browser-test`, using disposable Podman browser
  tooling and non-default ports; and
- the dedicated `todo-app` profile must run backend tests and the project-owned
  browser test, which installs dependencies and builds inside Podman, so the
  same cross-boundary claim is durable developer and milestone verification
  evidence.

The dependency diagnostic behaved as intended in the failed target: the four
direct Node dependencies were attributed once to the T0002 developer session,
with no lockfile/transitive entries and no repetition by later roles.

## Second live outcome and grader correction — 2026-08-22

The revised target completed in ten sessions. Its reviewer rejected T0002 once
for a missing required `src/App` component, the developer corrected it, and
target-owned browser validation passed during both developer attempts and
milestone integration. The independent check nevertheless exited before browser
launch because the target legitimately declared `@playwright/test` 1.62.1 while
the grader used a Playwright 1.53.1 image/client. Node resolved the target-local
1.62.1 `playwright` package before the grader's `NODE_PATH`, so it requested
browser binaries absent from the pinned 1.53.1 image.

This was a grader error, not an observed product failure. The check now imports
the evaluator-owned Playwright package by absolute path, wraps browser launch in
its diagnostic boundary, preserves unexpected top-level errors, and classifies
marked setup failures as `grader_error`. Evaluation checks now expose additive
`passed`, `failed`, `unverified`, and `grader_error` statuses while retaining the
Boolean `passed` field. Incomplete grading makes correctness indeterminate unless
a separate product check actually failed.

The general implication is that read-only mounts protect targets from mutation
but do not isolate evaluator dependency resolution. Evaluator runtimes must not
resolve libraries or executables through target-controlled working directories
or search paths.

After applying the evaluator correction, the independent browser check passed
against the unchanged retained target. This confirms that the revised generated
product satisfies the browser flow and that the recorded second-run failure was
entirely grader infrastructure. The original evaluation JSON remains immutable
failure evidence; the diagnostic rerun is correction evidence, not a rewritten
workflow result.

## Cross-scenario audit — 2026-08-22

The failure supports a general planning and review rule: validation should cross
the same boundary as the behavior it claims to verify. This rule now appears in
the shared conventions and planner, reviewer, and integrator instructions. It
does not add task metadata or a prose-based validator.

The existing evaluation families were checked for analogous gaps:

- stateful API checks already cross the process/HTTP boundary;
- compiled-language checks already build and invoke the generated executable;
- React/Vite now crosses the browser/Vite/API boundary in both target-owned and
  independent validation;
- the static-frontend scenario still checks its browser code structurally rather
  than running a browser flow, so its current claims should remain a structural
  baseline until live evidence justifies adding browser infrastructure; and
- deployment scenarios distinguish artifact checks from optional tool-backed
  verification and must not claim runtime deployment correctness when only
  artifact structure was checked.

One failed scenario is not sufficient evidence for structured verification-claim
metadata. Revisit that design only if additional labeled failures show that the
existing profile/task commands plus explicit unverified reporting cannot express
the needed contract reliably.

## Goal

Extend the opt-in `live-react-vite-todo-app-happy-path` evaluation so it proves
the generated React/Vite frontend runs in a browser and talks to the generated
Python todo API through the configured development-server integration.

The current live evaluation already checks the API behavior, React/Vite project
shape, and isolated frontend build in a disposable Podman Node container. This
plan adds the next confidence layer: run the API, run the Vite dev server, open
the app in a real browser, and exercise the todo workflow through the UI.

## What This Should Prove

- The generated React app starts under Vite.
- The browser can load the app without module, import, or runtime errors.
- The app can reach the Python API through the generated dev-server integration,
  such as Vite proxy configuration or CORS-safe absolute API URLs.
- The user-visible todo flow works: initial empty state, add item, list item,
  delete item, and display validation errors for invalid input.
- Browser console and page errors are captured in evaluation failures.

## Non-goals

- Do not judge visual design quality beyond basic visibility and layout smoke
  checks.
- Do not require production deployment behavior in this evaluation.
- Do not install target frontend dependencies on the host or in the temporary
  target repository.
- Do not make browser checks part of default pytest execution; keep them under
  the existing live-evaluation opt-in.
- Do not require a specific UI copy string beyond stable selectors or accessible
  labels requested by the scenario spec.

## Proposed Approach

Add a container-backed browser integration check for the React/Vite live
scenario.

The check should:

1. Mount the generated target repository read-only into a Podman container.
2. Copy the target into container-local `/tmp/work`.
3. Install frontend dependencies inside `/tmp/work` using `npm ci` when a
   lockfile exists, otherwise `npm install`.
4. Install or use browser tooling inside the container without mutating the host.
5. Start the Python todo API on an internal container port.
6. Start the Vite dev server on an internal container port.
7. Drive a browser against the Vite server.
8. Fail with captured stdout, stderr, browser console errors, and page errors
   when the UI contract fails.

Prefer a single container at first. Running API, Vite, and browser automation in
one container keeps network semantics simple: the browser can access Vite at
`127.0.0.1`, and Vite can proxy or fetch the API at another localhost port. If a
single image becomes unwieldy, split later into a small generated test runner
container and an app container network.

## Scenario Contract Changes

Tighten the React/Vite live scenario spec to require browser-testable affordances:

- The Vite dev server must be runnable with `npm run dev -- --host 127.0.0.1
  --port <port>`, or the README/package scripts must document an equivalent.
- The app must expose stable accessible controls:
  - a todo title input with an accessible name containing `todo` or `title`
  - an add/submit button
  - delete buttons associated with rendered todo items
  - a visible error region for validation failures
- API integration must work when the API runs on a separate arbitrary localhost
  port during development. Browser code calls same-origin `/todos` and `/health`
  routes, and Vite proxies them to the target supplied through `API_BASE_URL`.
- The generated project must own a `make browser-test` check that exercises the
  browser/Vite/API boundary with non-default ports in disposable Podman tooling
  and builds the frontend before starting it.
- The `todo-app` task profile must include `make test` and `make browser-test` as
  default validation. It must not require host-installed target npm dependencies.

Keep the contract permissive enough for different React implementations, but
specific enough that Playwright-style selectors can be reliable.

## Harness Design

Add a new check in `tests/evaluations/checks.py`, likely named
`react_vite_browser_integration_check`.

Implementation sketch:

```text
podman run --rm --pull=missing \
  -v <target>:/workspace:ro \
  <node-python-browser-image> \
  sh -lc '<copy target; npm install; install browser deps; start api; start vite; run browser script>'
```

Container command responsibilities:

- Copy `/workspace/.` to `/tmp/work`.
- Run frontend install in `/tmp/work`.
- Start the API with `python -m src.todo_api.server --port 8765`.
- Wait for `GET /health`.
- Start Vite with a fixed port, for example `npm run dev -- --host 127.0.0.1
  --port 5173`.
- Wait for the Vite page.
- Run a small browser automation script that:
  - opens `http://127.0.0.1:5173`
  - records console/page errors
  - submits an empty todo and expects a visible error
  - submits `write browser eval`
  - verifies the item appears
  - deletes the item
  - verifies the item disappears

The check should keep host assumptions explicit:

- Podman is required for this live check.
- Host npm/Node are not used by the check.
- Target dependencies are installed only inside the container-local copy.
- Podman image/layer cache may be used on the host.

## Browser Tooling Options

Preferred first implementation: use a Playwright-capable container image, such as
`mcr.microsoft.com/playwright:<version>`, if it can also run the generated Python
standard-library API. If the image lacks Python in the right shape, install
Python inside the container command or use a small project-owned generated
Containerfile for the check.

Fallback implementation: use a Node image and install Playwright plus browser
dependencies inside the container. This is slower and noisier, but still keeps
target dependencies off the host.

Avoid host Playwright/browser dependencies in the first version.

## Failure Diagnostics

On failure, report:

- target root path
- full Podman command shape without secrets
- API stdout/stderr tail
- Vite stdout/stderr tail
- browser console messages
- page errors
- failing selector/action
- whether dependency install, API startup, Vite startup, or browser flow failed

The diagnostics should be compact enough for pytest output but detailed enough
to avoid manual container debugging for common failures.

## Tests

Add focused tests for the new check:

- skipped or failed prerequisite behavior when Podman is unavailable, depending
  on whether this remains a hard requirement for the React/Vite live scenario
- command uses a read-only `/workspace` mount
- command copies the target into container-local `/tmp/work`
- command starts both API and Vite before running the browser flow
- command failure includes stdout/stderr tails
- live test module still imports and skips by default when live env vars are not
  set

Do not run a real browser or Podman container in default tests.

## Open Decisions

- Should missing Podman fail the React/Vite live evaluation or report
  skipped/unverified? Since the user explicitly assumes common host tooling for
  this scenario, failing with a clear prerequisite message is acceptable.
- Which container image should be standard? Prefer one image for reproducibility,
  but pinning the image tag may require periodic updates.
- The scenario uses a Vite proxy configured through `API_BASE_URL`; the first
  live result showed that allowing both proxy and cross-origin browser strategies
  left an important configuration branch unverified.
- Should this browser check replace the existing container build check or run
  after it? Initially keep both only if failure messages remain clearer; otherwise
  the browser check can subsume the build check because it must install and start
  Vite.

## Rollout

1. Add the browser integration check as a helper with unit tests around command
   construction and failure reporting.
2. Tighten the React/Vite live scenario spec for accessible selectors and dev API
   integration.
3. Wire the check into `live-react-vite-todo-app-happy-path`.
4. Update `docs/evaluations.md` with the stronger Podman/browser requirement.
5. Run default validation: Ruff, ty, scripted evaluation tests, and live test
   import/skip behavior.
6. Run one opt-in live React/Vite evaluation locally and record observations in a
   follow-up baseline document.
