# Deployment Specification — Stock Trading Strategy Backtester

The backtester is a desktop GUI application, not a network service. Deployment means packaging and distributing the application so users can install and run it on their own machines without needing a Python development environment.

## Deployment Targets

### 1. Python package (PyPI-ready sdist and wheel)

The primary distribution path. Users with Python installed can install via `pip install backtester` or `uv pip install backtester`.

Generated artifacts:

```
dist/
  backtester-<version>.tar.gz     # sdist
  backtester-<version>-py3-none-any.whl
```

The package must:
- Install all runtime dependencies (yfinance, pandas, matplotlib) automatically.
- Provide a console entry point `backtester` that launches the GUI, equivalent to `python -m backtester`.
- Include a `py.typed` marker if type annotations are used throughout.
- Use `uv build` for building and `uv publish` for uploading.

### 2. Standalone executable (PyInstaller)

For users without Python installed. Produce a self-contained single-directory bundle per platform.

Generated artifacts:

```
dist/
  backtester/               # single-directory bundle
    backtester              # (or backtester.exe on Windows)
    ...                     # bundled Python, dependencies, tkinter
```

The bundle must:
- Include the Python interpreter and all dependencies.
- Include tkinter (which is not always bundled with Python and must be explicitly included in the PyInstaller spec).
- Start the GUI when the executable is run — no terminal interaction required.
- Work on the build platform without additional installs.

Platform targets for the initial version: **Linux x86_64 only**. macOS and Windows builds are documented as future scope.

### 3. Flatpak (Linux desktop distribution)

For broader Linux distribution without requiring Python or pip. Flatpak provides sandboxing, desktop integration (application icon, `.desktop` file), and installation via Flathub or a local `.flatpak` file.

Generated artifacts:

```
packaging/flatpak/
  com.backtester.Backtester.yml     # Flatpak manifest
  com.backtester.Backtester.desktop # desktop entry
  com.backtester.Backtester.svg     # application icon (placeholder)
```

The Flatpak must:
- Use the `org.freedesktop.Sdk` and `org.freedesktop.Platform` runtimes.
- Bundle Python, pip dependencies, and tkinter inside the Flatpak sandbox.
- Declare `--share=network` permission (required for yfinance to reach Yahoo Finance).
- Provide a `.desktop` entry so the application appears in the system application menu.
- Build locally via `flatpak-builder`.

## Deployment Environments

| Environment | Purpose |
|-------------|---------|
| Local development | `uv run python -m backtester` — no packaging needed. |
| Local pip install | `uv pip install -e .` or `pip install dist/*.whl` — verify the package installs and the entry point works. |
| Local PyInstaller | Run the `dist/backtester/backtester` executable — verify the bundle starts the GUI. |
| Local Flatpak | `flatpak-builder --install --user` — verify the Flatpak builds, installs, and launches. |

All environments are local. There is no server, no container, no cloud deployment.

## Required Project Commands

The project Makefile must provide these targets:

```makefile
# Build the Python package (sdist + wheel)
make dist

# Run the application from source
make run

# Run the full test suite
make test

# Run linter and type checker
make lint

# Build the PyInstaller bundle
make bundle

# Build the Flatpak package
make flatpak

# Verify all deployment artifacts can be built
make deployment-verify

# Clean build artifacts
make clean
```

### Command details

**`make dist`** — runs `uv build` to produce sdist and wheel in `dist/`. Verifies the wheel is present and non-empty.

**`make run`** — runs `uv run python -m backtester`. Convenience target for development.

**`make test`** — runs `uv run pytest`. All tests must pass before any packaging step.

**`make lint`** — runs `uv run ruff check` and `uv run ty check` (or `uv run mypy` if ty is not available).

**`make bundle`** — runs PyInstaller with a `.spec` file to produce the standalone bundle in `dist/backtester/`. Requires PyInstaller in the dev dependency group.

**`make flatpak`** — runs `flatpak-builder` to build the Flatpak from the manifest in `packaging/flatpak/`. The build output goes to `build/flatpak/`.

**`make deployment-verify`** — runs the following checks in order:
1. `make test` — tests pass.
2. `make lint` — no lint or type errors.
3. `make dist` — sdist and wheel build successfully.
4. Verify the wheel can be installed in a fresh temporary venv and the `backtester` entry point exists.
5. `make bundle` — PyInstaller bundle builds successfully.
6. Verify the bundle executable exists and is executable.
7. If `flatpak-builder` is available: `make flatpak` — Flatpak builds successfully. If not available: print a warning and skip.

**`make clean`** — removes `dist/`, `build/`, `*.egg-info`, `__pycache__`, PyInstaller temp files, and Flatpak build directories.

## Verification Expectations

### Layer 1: Artifact validation (no external tools beyond Python)

These checks run during `make deployment-verify` and in CI:

- `uv build` succeeds and produces a `.whl` file.
- The wheel installs in an isolated venv without errors.
- The installed package exposes the `backtester` console entry point.
- `python -c "from backtester import __version__; print(__version__)"` succeeds after install.
- PyInstaller `.spec` file exists and is syntactically valid.
- `pyinstaller backtester.spec` succeeds and produces an executable.
- The executable file has the correct permissions (mode 755 on Linux).

### Layer 2: Functional smoke test

These checks verify the application can start:

- The `backtester` entry point opens the tkinter main window without crashing. Since the GUI requires a display, the smoke test imports the application module and verifies that the `App` class can be instantiated (with `withdraw()` to avoid showing the window) on systems with a display, or skips gracefully on headless systems.
- The PyInstaller bundle, when run, opens the same main window.
- The Flatpak, when installed, appears in `flatpak list` and can be launched via `flatpak run com.backtester.Backtester`.

### Layer 3: Host-tool-dependent checks

These checks are skipped if the required host tool is not installed, with a warning:

| Check | Required tool |
|-------|---------------|
| Flatpak build | `flatpak-builder` |
| PyInstaller bundle | `pyinstaller` (installed as dev dependency) |

DevLab does not install these tools. If they are missing, it reports the check as unverified.

## Configuration

The backtester has no runtime configuration files, secrets, or environment variables required for basic operation. yfinance fetches public data from Yahoo Finance without authentication.

Optional environment variable:
- `BACKTESTER_CACHE_DIR` — directory for persistent data cache across application restarts. Defaults to `~/.cache/backtester/`. Not required for operation; if unset, caching is in-memory only.

## Versioning

Use semantic versioning. The version is defined in one place: `pyproject.toml` under `[project] version`. The `__init__.py` reads it at runtime via `importlib.metadata`.

The PyInstaller bundle and Flatpak manifest reference the same version from `pyproject.toml`.

## Project Layout with Deployment Artifacts

```
backtester/
├── pyproject.toml
├── Makefile
├── backtester.spec              # PyInstaller spec file
├── packaging/
│   └── flatpak/
│       ├── com.backtester.Backtester.yml
│       ├── com.backtester.Backtester.desktop
│       └── com.backtester.Backtester.svg
├── src/
│   └── backtester/
│       ├── __init__.py          # __version__ from importlib.metadata
│       ├── __main__.py
│       ├── data.py
│       ├── engine.py
│       ├── sweep.py
│       ├── indicators.py
│       ├── persistence.py
│       ├── strategy/
│       │   └── ...
│       └── gui/
│           └── ...
├── tests/
│   └── ...
├── dist/                        # built by `make dist` and `make bundle`
└── build/                       # PyInstaller and Flatpak build intermediates
```

## Production Scope

There is no production deployment. The backtester is an end-user desktop application. Distribution means publishing the package to PyPI and optionally providing standalone bundles for download. There is no server to operate, no infrastructure to manage, no secrets to rotate.

## Future Scope

- macOS and Windows PyInstaller bundles (requires cross-platform CI or build machines).
- macOS `.app` bundle with code signing.
- Windows installer (NSIS or MSI) wrapping the PyInstaller output.
- Flathub submission for the Flatpak.
- Auto-update mechanism checking PyPI for new versions.
