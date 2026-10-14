PYTHON ?= python3
SAMPLE ?= data/sample_leads.jsonl

# Offline demo: deterministic FakeProvider with deliberate fault injection so the
# retry and dead-letter paths show up in the numbers. No network, no API keys.
DEMO_ENV = LLM_PROVIDER=fake FAKE_FAILURE_RATE=0.35 FAKE_SEED=7 LLM_RETRY_BASE_DELAY=0.05

.PHONY: install test lint run demo clean

install:
	$(PYTHON) -m pip install -e ".[dev]"

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .
	$(PYTHON) -m mypy

run:
	$(PYTHON) -m leadflow serve --host 0.0.0.0 --port 8000

demo:
	$(DEMO_ENV) $(PYTHON) -m leadflow run --input $(SAMPLE) --fresh
	$(PYTHON) -m leadflow report

clean:
	rm -rf out .pytest_cache .ruff_cache .mypy_cache
