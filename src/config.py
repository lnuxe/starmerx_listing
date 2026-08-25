"""配置加载 + 日志工具。"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

# 项目根目录
ROOT = Path(__file__).resolve().parent.parent

# 日志
logger = logging.getLogger("starmerx")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(message)s"))  # 时间戳由 log() 统一加
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)


def log(msg: str, level: str = "info") -> None:
    """带时间戳的统一日志输出。"""
    ts = datetime.now().strftime("%H:%M:%S")
    getattr(logger, level)(f"{ts} | {msg}")


def load_config(path: str | Path | None = None) -> dict:
    """加载 config.json 并返回 dict。"""
    p = Path(path) if path else ROOT / "config.json"
    with open(p, encoding="utf-8") as f:
        return json.load(f)