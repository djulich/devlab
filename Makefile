.PHONY: help sync format check test install install-editable reinstall reinstall-editable uninstall

UV ?= uv
PACKAGE ?= devlab

help: ## Show available Makefile targets.
	@printf 'DevLab source checkout targets:\n\n'
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

sync: ## Install/update local development dependencies with uv.
	$(UV) sync

format: ## Format Python source and tests with Ruff.
	$(UV) run ruff format

check: ## Run formatting, lint, type checks, and the test suite.
	$(UV) run ruff format --check
	$(UV) run ruff check
	$(UV) run ty check
	$(UV) run pytest -q

test: ## Run the test suite.
	$(UV) run pytest -q

install: ## Install DevLab as a regular uv tool from this checkout.
	$(UV) tool install .

install-editable: ## Install DevLab as an editable uv tool for development.
	$(UV) tool install --editable .

# Force targets are useful after changing packaging metadata or switching
# between editable and non-editable installs of the same command.
reinstall: ## Force-reinstall DevLab as a regular uv tool from this checkout.
	$(UV) tool install --force .

reinstall-editable: ## Force-reinstall DevLab as an editable uv tool.
	$(UV) tool install --force --editable .

uninstall: ## Remove the uv-managed DevLab tool.
	$(UV) tool uninstall $(PACKAGE)
