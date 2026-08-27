"""临时测试：单行端到端跑 _check_price（dry-run，不保存）。"""
from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

from src.config import load_config, log, ROOT
from src.login import _open_context, is_logged_in
from src.phase2 import _open_plan_page, _check_price


def main() -> None:
    config = load_config()
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
        log(f"=== _check_price(row0) 结果 ===")
        if issues:
            for it in issues:
                log(f"  ✗ {it}")
        else:
            log("  ✓ 无问题（价格/利润闭环通过）")

        browser.close()


if __name__ == "__main__":
    main()