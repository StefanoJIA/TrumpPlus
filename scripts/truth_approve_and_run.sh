#!/bin/bash
# 仅用于 local/test 环境，staging/production 禁止使用
set -e
cd /Users/ruopeng/Projects/TrumpPlus
source .venv/bin/activate
set -a
source .env
set +a

echo "=== Step 1: approve truth_fetcher 来源 ==="
python -m app.jobs.daily_run_orchestrator \
  --date today \
  --mode local-auto \
  2>&1 | tail -30

echo "=== Step 2: 查看 daily run report ==="
cat exports/daily_runs/$(date +%Y-%m-%d)/DAILY_RUN_REPORT.md \
  2>/dev/null || echo "report 未生成，请检查上一步输出"

echo "=== Step 3: 检查 final video ==="
ls -lh exports/final_videos/ 2>/dev/null || echo "暂无 final video"
