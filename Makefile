# Everything a fresh clone needs, in the order you would need it.
.PHONY: help install data api web test check eval eval-docs docker

PY := .venv/bin/python

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-12s %s\n", $$1, $$2}'

install:  ## create the venv and install the package with dev and agent extras
	python3 -m venv .venv
	$(PY) -m pip install -q -e '.[dev,agent]'
	cd frontend && npm install --no-audit --no-fund

data:  ## build the committed sample into a queryable database
	$(PY) -m flightops.ingest.sample

api: data  ## run the API on :8000 against the sample
	.venv/bin/uvicorn flightops.api.app:app --reload --port 8000

web:  ## run the frontend on :3000 against a local API
	cd frontend && NEXT_PUBLIC_API_URL=http://127.0.0.1:8000 npm run dev

test:  ## the whole suite, offline
	$(PY) -m pytest -q

check:  ## lint, types, tests, and the frontend typecheck
	$(PY) -m ruff format --check src tests scripts
	$(PY) -m ruff check src tests scripts
	$(PY) -m mypy
	$(PY) -m pytest -q
	cd frontend && npm run lint

eval:  ## live eval run; needs ANTHROPIC_API_KEY, costs money
	$(PY) scripts/run_eval.py

eval-docs:  ## regenerate docs/EVAL.md from the eval set
	$(PY) scripts/run_eval.py --docs

docker:  ## build the API image exactly as the deploy does
	docker build -t flightops-api .
