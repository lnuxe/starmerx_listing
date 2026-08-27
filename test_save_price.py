"""真实保存算价结果：跑 _check_price(row0) 并点「保存算价结果」。

截图归纳到 runtime/本轮截图/：
  10_保存前_利润已调整.png
  11_点击保存算价结果后.png
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from src.config import load_config, log, ROOT
from src.login import _open_context, is_logged_in
from src.phase2 import _open_plan_page, _check_price

SHOT_DIR = ROOT / "runtime" / "本轮截图"


def shot(page, name: str) -> None:
    p = SHOT_DIR / name
    page.screenshot(path=str(p), full_page=True)
    log(f"[截图] {name}")


def main() -> None:
    config = load_config()
    # 临时关闭 dry_run，触发真实「保存算价结果」
    config["safety"]["dry_run"] = False

    with sync_playwright() as p:
        browser, context = _open_context(
            p, config, headless=config["app"]["headless"],
            storage=ROOT / config["app"]["storage_state"],
        )
        page = context.new_page()
        if not is_logged_in(page):
            log("✗ 未登录"); browser.close(); sys.exit(1)

        _open_plan_page(page, config)
        page.wait_for_timeout(2000)
        try:
            page.locator(".vxe-table--body-wrapper tr").first.wait_for(
                state="attached", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(1000)

        issues = _check_price(page, config, row_idx=0)
        log("=== _check_price(row0) 真实保存 结果 ===")
        if issues:
            for it in issues:
                log(f"  ✗ {it}")
        else:
            log("  ✓ 无问题（价格/利润闭环通过，已保存算价结果）")

        shot(page, "11_点击保存算价结果后.png")
        browser.close()


if __name__ == "__main__":
    main()