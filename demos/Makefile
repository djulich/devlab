.PHONY: help check

UV ?= uv

help: ## Show available demo validation targets.
	@printf 'DevLab repository demo targets:\n\n'
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_-]+:.*## / {printf "  %-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

check: ## Validate all repository-only demo packages.
	$(UV) run ruff format --check system-evolution/grader
	$(UV) run ruff check system-evolution/grader
	$(UV) run ty check system-evolution/grader
	$(UV) run pytest -q system-evolution/grader
