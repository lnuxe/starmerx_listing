"""有头模式勘察产品池，等待网络空闲+更长超时，确认是否真有数据。

用 headless=False 模拟真实浏览器，等待 networkidle 和额外渲染时间。
"""
import re
from playwright.sync_api import sync_playwright
from src.config import load_config, ROOT
from src.login import _open_context

base = "https://op.starmerx.com/#/sale-manage/my-product"

with sync_playwright() as p:
    browser, context = _open_context(p, load_config(), headless=False,
                                     storage=ROOT / "runtime/storage_state.json")
    page = context.new_page()

    # 监听网络响应，看产品列表接口是否返回数据
    api_responses = []

    def on_response(resp):
        url = resp.url
        if "product" in url.lower() or "list" in url.lower() or "page" in url.lower():
            try:
                body = resp.text()
            except Exception:
                body = ""
            api_responses.append((url[:120], body[:500]))

    page.on("response", on_response)

    page.goto(base, wait_until="domcontentloaded", timeout=60000)
    print("已加载，等待网络空闲...")
    try:
        page.wait_for_load_state("networkidle", timeout=30000)
    except Exception:
        print("网络未完全空闲，继续等待渲染")
    page.wait_for_timeout(8000)  # 额外等渲染

    print("最终URL:", page.url)
    body = page.evaluate("() => document.body.innerText")
    m = re.search(r"共\s*(\d+)\s*条", body)
    print("记录总数:", m.group(1) if m else "N/A")

    print("\n=== 捕获到的相关API响应 ===")
    for u, b in api_responses[:15]:
        print("URL:", u)
        print("BODY:", b[:300].replace(chr(10), " "))
        print("-" * 60)

    page.screenshot(path=str(ROOT / "runtime/product_pool_headful.png"), full_page=True)
    print("\n已截图 runtime/product_pool_headful.png")
    browser.close()