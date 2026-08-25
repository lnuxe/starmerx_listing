"""验证：选中叶子「圣诞节花环」后产品池有多少行。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright

from src.config import load_config, log, ROOT
from src.login import _open_context, is_logged_in
from src.dom import wait_network_idle_light
from src.phase1 import SEL_TAB_US_POOL, SEL_TAB_CHANNEL, SEL_SEARCH_BTN, SEL_TABLE

PATH = ["家居、厨具、家装", "节日饰品", "圣诞花环、花带装饰和垂花饰", "圣诞节花环"]


def main() -> None:
    config = load_config()
    with sync_playwright() as p:
        browser, context = _open_context(p, config, headless=True,
                                         storage=ROOT / config["app"]["storage_state"])
        page = context.new_page()
        if not is_logged_in(page):
            log("✗ 未登录")
            browser.close()
            sys.exit(1)

        pool = config["product_pool"]
        page.goto(pool["url"], wait_until="domcontentloaded", timeout=60000)
        wait_network_idle_light(page)
        page.click(SEL_TAB_US_POOL)
        page.wait_for_timeout(1500)
        try:
            page.click(SEL_TAB_CHANNEL, timeout=5000)
        except Exception:
            pass
        page.wait_for_timeout(1200)

        from src.phase1 import _open_category
        _open_category(page, PATH)
        page.wait_for_timeout(1000)
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)

        val = page.evaluate(
            """() => { const c = document.querySelector('.el-cascader .el-input__inner'); return c ? c.value : null; }"""
        )
        log(f"品类输入框回填值: {val!r}")

        page.click(SEL_SEARCH_BTN)
        page.wait_for_timeout(5000)
        n = page.locator(SEL_TABLE).first.locator("tr").count()
        log(f"搜索后行数: {n}")
        if n:
            for i in range(min(n, 3)):
                log(f"行{i}: {page.locator(SEL_TABLE).first.locator('tr').nth(i).inner_text()[:100]}")
        browser.close()


if __name__ == "__main__":
    main()