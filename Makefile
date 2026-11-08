# EdgeForge Studio — developer convenience targets. Python 3.11+.

PY ?= python3.11
VENV ?= .venv

.PHONY: setup run test lint sbom audit lock clean

setup:        ## create venv and install requirements
	$(PY) -m venv $(VENV)
	$(VENV)/bin/python -m pip install -c constraints.txt pip setuptools wheel
	$(VENV)/bin/python scripts/verify-packaging-toolchain.py
	$(VENV)/bin/python -m pip install -r requirements.txt -c constraints.txt
	$(VENV)/bin/python -m pip install -e ".[dev]" -c constraints.txt

run:          ## start the local Studio web server
	$(VENV)/bin/uvicorn app.main:app --reload --port 8080

test:         ## run the test suite
	$(VENV)/bin/python -m pytest tests/ -q

lint:         ## run ruff lint locally
	$(VENV)/bin/ruff check .

sbom:         ## regenerate G4 dependency evidence (SBOM + license inventory)
	scripts/generate-dependency-evidence.sh

audit:        ## run dependency audit against the locked constraints
	$(VENV)/bin/pip-audit -r constraints.txt --no-deps --disable-pip --progress-spinner off

lock:         ## export resolved constraints from requirements.txt
	@set -e; \
	tmp="$$(mktemp -d)"; \
	trap 'rm -rf "$$tmp"' EXIT; \
	$(PY) -m venv "$$tmp/venv"; \
	"$$tmp/venv/bin/python" -m pip install -c constraints.txt pip setuptools wheel; \
	"$$tmp/venv/bin/python" scripts/verify-packaging-toolchain.py; \
	"$$tmp/venv/bin/python" -m pip install -r requirements.txt; \
	"$$tmp/venv/bin/python" -m pip freeze --all | sort -f > "$$tmp/constraints.txt"; \
	mv "$$tmp/constraints.txt" constraints.txt; \
	echo "wrote constraints.txt"

clean:        ## remove local caches and transient Python artifacts
	find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache \) -prune -exec rm -rf {} +
