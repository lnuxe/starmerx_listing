#!/bin/bash
# Starmerx 上架自动化 — 一键启动脚本
# 用法: ./run.sh <命令> [选项]
set -e
cd "$(dirname "$0")"
PY=".venv/bin/python"

usage() {
    cat <<'EOF'
Starmerx 上架自动化
用法: ./run.sh <命令> [选项]

命令:
  login            钉钉扫码登录（首次/过期）
  check-login      检测登录态是否有效
  probe-phase1     勘察产品池页（确认选择器，不修改数据）
  probe-phase2     勘察上架计划页
  phase1           产品池→加入上架计划
  phase2           图片/价格校验 + 批量上架
  all              全流程（登录检测→phase1→phase2）

选项:
  --no-dry-run     正式执行（默认干运行，只检查不上架）
  --max-sku N      最多处理 SKU 数（phase1）
EOF
}

CMD="${1:-help}"
shift || true

case "$CMD" in
  login)          $PY -m src.main login ;;
  check-login)    $PY -m src.main check-login ;;
  probe-phase1)   $PY -m src.main probe-phase1 ;;
  probe-phase2)   $PY -m src.main probe-phase2 ;;
  phase1)         $PY -m src.main phase1 "$@" ;;
  phase2)         $PY -m src.main phase2 "$@" ;;
  all)            $PY -m src.main all "$@" ;;
  help|-h|--help) usage ;;
  *) echo "未知命令: $CMD"; usage; exit 1 ;;
esac