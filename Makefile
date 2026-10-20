# MINDMAP — local ingest + web (MM-008)
# Bind the UI to 127.0.0.1 only. GitHub access is via `gh` login (no tokens).

.PHONY: refresh refresh-gh-ledger refresh-demo live test test-py test-web typecheck help

ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
OUT ?= $(ROOT)/web/public/activity.json
PYTHON ?= python3

help:
	@echo "Targets:"
	@echo "  make refresh          Build from \$$MINDMAP_LEDGER + gh PR poll"
	@echo "  make refresh-gh-ledger Build from data/ledger mirror + gh PR poll"
	@echo "  make refresh-demo     Offline: fixture ledger, skip GitHub"
	@echo "  make live             Live daemon: poll ledger/gh + serve web/dist on 127.0.0.1"
	@echo "  make test             pytest + web vitest"
	@echo "  make typecheck        shared + web TypeScript"
	@echo ""
	@echo "Dev UI (after refresh):  cd web && npm run dev"
	@echo "  (vite is bound to 127.0.0.1:5173)"

# Live Fencepost path: requires MINDMAP_LEDGER and an authenticated `gh` CLI.
refresh:
ifndef MINDMAP_LEDGER
	$(error Set MINDMAP_LEDGER to the absolute path of task-ledger.md)
endif
	$(PYTHON) -m ingest --ledger "$(MINDMAP_LEDGER)" --out "$(OUT)"

# Ledger from allowlisted data/ledger mirror (MM-010); still uses gh for PRs.
refresh-gh-ledger:
	$(PYTHON) -m ingest --ledger-source gh --out "$(OUT)"

# Offline / CI-friendly: schema-valid activity.json from committed fixtures.
# Uses --skip-github so no network or gh login is required.
refresh-demo:
	$(PYTHON) -m ingest \
		--ledger "$(ROOT)/tests/fixtures/ledger-sample.md" \
		--out "$(OUT)" \
		--skip-github

# Long-running: path ledger via MINDMAP_LEDGER, or gh mirror when unset.
live:
ifdef MINDMAP_LEDGER
	$(PYTHON) -m ingest.live --ledger "$(MINDMAP_LEDGER)"
else
	$(PYTHON) -m ingest.live --ledger-source gh
endif

test-py:
	$(PYTHON) -m pytest -q

test-web:
	cd "$(ROOT)/web" && npm test

test: test-py test-web

typecheck:
	npm run typecheck
	cd "$(ROOT)/web" && npm run typecheck
