.PHONY: install ingest context demo verify test spec-update

install:
	uv pip install --system -e "..[server,seekdb]" pytest

ingest:
	SDD_DB=seekdb python -m sdd_context ingest

context:
	SDD_DB=seekdb python -m sdd_context context --format markdown

demo:
	SDD_DB=seekdb python -m sdd_context demo --offline

verify:
	python -m sdd_context verify

test:
	python -m pytest demo_project/tests -q

spec-update:
	python scripts/spec_update_check.py
