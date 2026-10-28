.PHONY: install install-seekdb serve doctor ingest ask review demo test verify

install:
	pip install -e .

install-seekdb:
	pip install -e ".[seekdb]"

serve:
	python -m uvicorn wengu.api:app --host 0.0.0.0 --port 8000

doctor:
	python -m wengu.cli doctor

ingest:
	python -m wengu.cli ingest --sample

ask:
	python -m wengu.cli ask "Raft 里一条日志什么时候算已提交？" --top-k 5

review:
	python -m wengu.cli review

demo:
	python -m wengu.cli demo --out records

test:
	python -m pytest -q

verify: doctor ingest ask review test demo
	@echo "验证完成：看 records/demo_summary.json"
