"""验证修正后的 _run_checks：只处理目标品类草稿行，dry-run 试算。"""
from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

from src.config import load_config, log, ROOT
from src.login import _open_context, is_logged_in
from src.phase2 import _open_plan_page, _run_checks


def main() -> None:
    config = load_config()
    config["safety"]["dry_run"] = True   # 确保 dry-run，不保存
    with sync_playwright() as p:
        browser, context = _open_context(
            p, config, headless=False,
            storage=ROOT / config["app"]["storage_state"],
        )
        page = context.new_page()
        if not is_logged_in(page):
            log("✗ 未登录"); browser.close(); sys.exit(1)

        _open_plan_page(page, config)
        page.wait_for_timeout(2000)

        report = _run_checks(page, config)
        log("=== _run_checks 结果 ===")
        log(f"通过 {report['ok_spus']} / 问题 {report['fail_spus']}")
        if report["price_issues"]:
            for it in report["price_issues"]:
                log(f"  问题: {it}")

        browser.close()


if __name__ == "__main__":
    main()