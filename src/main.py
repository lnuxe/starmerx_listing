"""Starmerx 上架自动化 — 主入口（编排四阶段）。

用法：
    python -m src.main login            # 扫码登录
    python -m src.main check-login      # 检测登录态
    python -m src.main probe-phase1     # 勘察产品池页
    python -m src.main probe-phase2     # 勘察上架计划页
    python -m src.main phase1 [--no-dry-run] [--max-sku N]   # 产品池→加入计划
    python -m src.main phase2 [--probe] [--no-dry-run]        # 图片/价格校验
    python -m src.main all [--no-dry-run] [--max-sku N]       # 全流程

所有阶段默认 dry_run（只检查不批量上架）；加 --no-dry-run 才真正执行。
"""
from __future__ import annotations

import sys

from src.config import load_config, log
from src import login as login_mod
from src import phase1 as phase1_mod
from src import phase2 as phase2_mod


def main() -> None:
    config = load_config()
    args = sys.argv[1:]
    cmd = args[0] if args else "help"

    if cmd == "login":
        login_mod.do_login(config)
    elif cmd == "check-login":
        sys.exit(0 if login_mod.check_login(config) else 1)
    elif cmd in ("probe-phase1", "probe1"):
        sys.argv = [sys.argv[0], "--probe"] + args[1:]
        phase1_mod.main()
    elif cmd in ("probe-phase2", "probe2"):
        sys.argv = [sys.argv[0], "--probe"] + args[1:]
        phase2_mod.main()
    elif cmd == "phase1":
        sys.argv = [sys.argv[0]] + args[1:]
        phase1_mod.main()
    elif cmd == "phase2":
        sys.argv = [sys.argv[0]] + args[1:]
        phase2_mod.main()
    elif cmd == "all":
        _run_all(config, args)
    else:
        print(__doc__)


def _run_all(config: dict, args: list[str]) -> None:
    """全流程编排：登录检测 → phase1 → phase2。"""
    log("[all] === 开始全流程 ===")
    if not login_mod.check_login(config):
        log("[all] ✗ 登录态无效，请先 `python -m src.main login`")
        sys.exit(1)
    # 透传剩余参数（--no-dry-run / --max-sku）给 phase1
    sys.argv = [sys.argv[0]] + args[1:]
    phase1_mod.main()
    log("[all] Phase1 完成，进入 Phase2 校验...")
    # 透传 --no-dry-run 给 phase2（phase2 只关心 dry_run，忽略 --max-sku）
    sys.argv = [sys.argv[0]] + [a for a in args[1:] if a in ("--no-dry-run",)]
    phase2_mod.main()
    log("[all] === 全流程结束 ===")


if __name__ == "__main__":
    main()