"""测试：带成功案例的完整参数 URL（无 arrivedKey/storageKey）能否加载美区产品池。"""
import re
from playwright.sync_api import sync_playwright
from src.config import load_config, ROOT
from src.login import _open_context

urls = [
    # 成功案例参数（有头模式自然跳转得到）
    "https://op.starmerx.com/#/sale-manage/my-product?currentPage=1&pageSize=20&filter_type=sku_codes&warehouse_location_id=0&inventoryType=inventory&turnoverType=inventory&priceType=starmerx&date_type=first_entry_time",
    # 最简 URL
    "https://op.starmerx.com/#/sale-manage/my-product",
]

with sync_playwright() as p:
    browser, context = _open_context(p, load_config(), headless=True,
                                     storage=ROOT / "runtime/storage_state.json")
    for idx, base in enumerate(urls):
        page = context.new_page()
        page.goto(base, wait_until="domcontentloaded", timeout=60000)
        total = "N/A"
        for i in range(12):
            page.wait_for_timeout(1000)
            body = page.evaluate("() => document.body.innerText")
            m = re.search(r"共\s*(\d+)\s*条", body)
            if m:
                total = m.group(1)
                if total != "0":
                    break
        print(f"[URL{idx}] 记录数: {total}")
        print(f"  最终URL: {page.url[:140]}")
        page.close()
    browser.close()