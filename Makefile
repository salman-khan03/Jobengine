.PHONY: install dev fetch build query tailor audit test lint typecheck check clean

install:
	pip install -e .

dev:
	pip install -e ".[dev]"

fetch:
	jobengine fetch

build:
	jobengine build

query:
	jobengine query --summary

audit:
	jobengine audit

test:
	pytest -v

lint:
	ruff check src/ tests/

typecheck:
	mypy src/jobengine --ignore-missing-imports

check: lint typecheck test   ## everything CI runs, locally, before you push

clean:
	rm -rf data tailored *.db __pycache__ .pytest_cache .mypy_cache .ruff_cache \
		src/jobengine/__pycache__ tests/__pycache__ *.egg-info
