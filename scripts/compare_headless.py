"""对照测试：同一 storage_state，有头 vs 无头，加载基础 URL，对比最终 URL 与记录数。"""
import re
from playwright.sync_api import sync_playwright
from src.config import load_config, ROOT
from src.login import _open_context

base = "https://op.starmerx.com/#/sale-manage/my-product"


def run(headless: bool):
    with sync_playwright() as p:
        browser, context = _open_context(p, load_config(), headless=headless,
                                         storage=ROOT / "runtime/storage_state.json")
        page = context.new_page()
        page.goto(base, wait_until="domcontentloaded", timeout=60000)
        for i in range(15):
            page.wait_for_timeout(1000)
            body = page.evaluate("() => document.body.innerText")
            m = re.search(r"共\s*(\d+)\s*条", body)
            if m and m.group(1) != "0":
                total = m.group(1)
                break
            total = m.group(1) if m else "N/A"
        print(f"[headless={headless}] 记录数: {total}")
        print(f"  最终URL: {page.url[:150]}")
        # 看当前激活的标签页
        active = page.evaluate("""() => {
            const t = document.querySelector('.el-tabs__item.is-active, .vxe-tabs__item.is-active, [class*=active]');
            return t ? t.innerText.trim() : 'N/A';
        }""")
        print(f"  激活标签: {active}")
        browser.close()


run(headless=True)
run(headless=False)