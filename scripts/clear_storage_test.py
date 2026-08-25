"""验证：清空 session/localStorage 后能否加载出美区产品池数据。"""
import re
from playwright.sync_api import sync_playwright
from src.config import load_config, ROOT
from src.login import _open_context

base = "https://op.starmerx.com/#/sale-manage/my-product"

with sync_playwright() as p:
    browser, context = _open_context(p, load_config(), headless=True,
                                     storage=ROOT / "runtime/storage_state.json")
    page = context.new_page()

    # 先访问空页面清空该 origin 的 storage，再加载目标页
    page.goto("https://op.starmerx.com/", wait_until="domcontentloaded", timeout=30000)
    page.evaluate("""() => {
        try { sessionStorage.clear(); } catch(e) {}
        try { localStorage.clear(); } catch(e) {}
    }""")
    print("已清空 op.starmerx.com 的 session/localStorage")

    page.goto(base, wait_until="domcontentloaded", timeout=60000)
    for i in range(20):
        page.wait_for_timeout(1000)
        body = page.evaluate("() => document.body.innerText")
        m = re.search(r"共\s*(\d+)\s*条", body)
        if m and m.group(1) != "0":
            print(f"第{i+1}秒: 共 {m.group(1)} 条")
            print("URL:", page.url[:120])
            break
        if i == 19:
            print("20秒后仍无数据")
            print("最终URL:", page.url[:150])
    browser.close()