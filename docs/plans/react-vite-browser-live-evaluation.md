# React/Vite Browser Live Evaluation Plan

Status: implemented.

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
- API integration must work when the API runs on a separate localhost port during
  development. Acceptable implementations include:
  - Vite proxy configuration for `/todos` and `/health`
  - documented environment variable for API base URL that the check can set
  - same-origin serving only if the scenario also provides a dev command that
    serves built assets and API together

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
- Should the scenario require Vite proxy configuration, or allow API base URL
  environment variables? The first version can allow both if the browser check
  can configure either path deterministically.
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
