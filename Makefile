# Retail Intelligence — local development entry points.
#
# Three Python environments, deliberately separate (decision #38):
#   datagen/.venv     source generator, imports nothing downstream
#   ingestion/.venv   landing -> gates -> staging -> transforms -> curated
#   ml/.venv          curated consumers (Phase 3 onward)
# Both ingestion and ml install the two shared packages: retail-contracts
# (semantics) and retail-intelligence-execution (bounded throughput).
#
# This Makefile is an optional POSIX convenience wrapper. The authoritative,
# Windows-compatible interface is:
#   py -3 tools/dev.py <command>

PYTHON    ?= python3
DEV       := $(PYTHON) tools/dev.py

PROFILE   ?= safe
SOURCE_ROOT ?=
LANDING_ROOT ?= ingestion/data/raw

.DEFAULT_GOAL := help
.PHONY: help envs boundaries wheels wheels-offline test test-pinned-run contracts \
        land gate-a gate-b bench lint-plan config-hash run-status clean-envs

help: ## Show available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------- environments

envs: ## Create/refresh the ingestion and ml environments
	$(DEV) envs

clean-envs: ## Remove the ingestion and ml environments (datagen/.venv is left alone)
	rm -rf ingestion/.venv ml/.venv

# ---------------------------------------------------------------- verification

boundaries: ## Enforce package ownership boundaries statically
	$(DEV) boundaries

wheels: ## Build actual wheels and prove each distribution installs in isolation
	$(DEV) wheels

wheels-offline: ## Run the actual-wheel check without resolving external dependencies
	$(DEV) wheels --offline

test: ## Run every fast suite
	$(DEV) test

test-pinned-run: ## Pinned-run acceptance only
	$(DEV) test --pinned-only

# ---------------------------------------------------------------- source data

config-hash: ## Print the pinned scenario's pre-generation identity
	$(DEV) config-hash

run-status: ## Show whether the pinned run has promoted yet
	$(DEV) run-status

# ---------------------------------------------------------------- phase 2

contracts: ## Validate the machine-readable contract
	$(DEV) contracts

land: ## Land SOURCE_ROOT immutably into LANDING_ROOT
	$(DEV) land --execution-profile $(PROFILE) --source-root "$(SOURCE_ROOT)" --landing-root "$(LANDING_ROOT)"

gate-a: ## Run Gate A (fails explicitly until W2 lands)
	$(DEV) gate-a --execution-profile $(PROFILE)

gate-b: ## Run Gate B (fails explicitly until W4 lands)
	$(DEV) gate-b --execution-profile $(PROFILE)

bench: ## Run per-stage benchmarks (fails explicitly until W5 lands)
	$(DEV) bench --execution-profile $(PROFILE)

lint-plan: ## Check patch/Markdown whitespace
	git diff --check
