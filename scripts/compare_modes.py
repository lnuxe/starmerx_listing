"""对照测试：不同方式加载美区产品池，找到稳定出数据的路径。

方式A: 基础URL + 点击"美区产品池"标签
方式B: 成功案例完整参数URL
方式C: 基础URL + field_type=sku_codes(复数)
"""
import re
import sys
from playwright.sync_api import sync_playwright
from src.config import load_config, ROOT
from src.login import _open_context

BASE = "https://op.starmerx.com/#/sale-manage/my-product"
URL_B = ("https://op.starmerx.com/#/sale-manage/my-product"
         "?filter_type=sku_codes&warehouse_location_id=0&inventoryType=inventory"
         "&turnoverType=inventory&priceType=starmerx&date_type=first_entry_time")
URL_C = "https://op.starmerx.com/#/sale-manage/my-product?currentPage=1&pageSize=20&field_type=sku_codes"


def get_total(page):
    body = page.evaluate("() => document.body.innerText")
    m = re.search(r"共\s*(\d+)\s*条", body)
    return m.group(1) if m else "N/A"


def run(mode: str):
    with sync_playwright() as p:
        browser, context = _open_context(p, load_config(), headless=True,
                                         storage=ROOT / "runtime/storage_state.json")
        page = context.new_page()

        if mode == "A":
            page.goto(BASE, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
            # 点击"美区产品池"标签
            try:
                page.click('.el-tabs__item:has-text("美区产品池")', timeout=8000)
                print("A: 已点击美区产品池标签")
            except Exception as e:
                print("A: 点标签失败", str(e)[:60])
            for i in range(12):
                page.wait_for_timeout(1000)
                t = get_total(page)
                if t != "0" and t != "N/A":
                    print(f"A: 第{i+1}秒 共 {t} 条")
                    break
            else:
                print(f"A: 12秒后 {get_total(page)} 条")
            print("A 最终URL:", page.url[:110])

        elif mode == "B":
            page.goto(URL_B, wait_until="domcontentloaded", timeout=60000)
            for i in range(12):
                page.wait_for_timeout(1000)
                t = get_total(page)
                if t != "0" and t != "N/A":
                    print(f"B: 第{i+1}秒 共 {t} 条")
                    break
            else:
                print(f"B: 12秒后 {get_total(page)} 条")
            print("B 最终URL:", page.url[:110])

        elif mode == "C":
            page.goto(URL_C, wait_until="domcontentloaded", timeout=60000)
            for i in range(12):
                page.wait_for_timeout(1000)
                t = get_total(page)
                if t != "0" and t != "N/A":
                    print(f"C: 第{i+1}秒 共 {t} 条")
                    break
            else:
                print(f"C: 12秒后 {get_total(page)} 条")
            print("C 最终URL:", page.url[:110])

        browser.close()


if __name__ == "__main__":
    for m in ["A", "B", "C"]:
        print(f"===== 方式{m} =====")
        run(m)