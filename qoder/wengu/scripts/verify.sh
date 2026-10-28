#!/usr/bin/env bash
# 一条命令复现全部验证：自检 → 导入 → 提问 → 复习 → 端到端 → 单测
# 用法： WENGU_STORE=seekdb ./scripts/verify.sh [输出目录]
set -euo pipefail
cd "$(dirname "$0")/.."

OUT="${1:-records}"
export WENGU_STORE="${WENGU_STORE:-auto}"
export PYTHONIOENCODING=utf-8

echo "== 0. 自检 =="
python -m wengu.cli doctor | tee /tmp/wengu-doctor.json

echo "== 1. 导入示例语料 =="
python -m wengu.cli ingest --sample | tee /tmp/wengu-ingest.json

echo "== 2. 带出处提问 =="
python -m wengu.cli ask "Raft 里一条日志什么时候算已提交？" --top-k 5

echo "== 3. 生成复习题 =="
python -m wengu.cli review

echo "== 4. 单元测试 =="
python -m pytest -q

echo "== 5. 端到端验证（含 PowerContext 重启与记忆复用） =="
python -m wengu.cli demo --out "$OUT"

echo "== 完成：$OUT/demo_summary.json =="
