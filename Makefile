.PHONY: help setup sync hooks format check test release-check install install-editable reinstall reinstall-editable uninstall

UV ?= uv
PACKAGE ?= devlab

help: ## Show available Makefile targets.
	@printf 'DevLab source checkout targets:\n\n'
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

setup: ## Initialize the development environment and install Git hooks.
	$(MAKE) sync
	$(MAKE) hooks

sync: ## Install/update local development dependencies with uv.
	$(UV) sync

hooks: ## Install repository-managed Git hooks in this clone.
	@set -eu; \
	hooks_dir="$$(git rev-parse --git-common-dir)/hooks"; \
	mkdir -p "$$hooks_dir"; \
	for hook in pre-commit pre-push; do \
		source="$(CURDIR)/.githooks/$$hook"; \
		target="$$hooks_dir/$$hook"; \
		if [ -e "$$target" ] || [ -L "$$target" ]; then \
			if [ ! -L "$$target" ] || [ "$$(readlink "$$target")" != "$$source" ]; then \
				echo "Refusing to replace existing Git hook: $$target" >&2; \
				exit 1; \
			fi; \
		else \
			ln -s "$$source" "$$target"; \
		fi; \
	done
	@echo "Installed pre-commit and pre-push hooks."

format: ## Format Python source and tests with Ruff.
	$(UV) run ruff format

check: ## Run formatting, lint, type checks, and the test suite.
	$(UV) run ruff format --check
	$(UV) run ruff check
	$(UV) run ty check
	$(UV) run pytest -q

test: ## Run the test suite.
	$(UV) run pytest -q

release-check: ## Build, inspect, install, and smoke-test release artifacts.
	$(UV) run python scripts/release_check.py

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
