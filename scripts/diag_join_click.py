"""诊断「直接加入上架计划」点击后的行为：监听 popup 新窗口 + 网络请求。
确认表单是以新窗口打开、抽屉、还是被拦截。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import sync_playwright

from src.config import load_config, log, ROOT
from src.login import _open_context, is_logged_in
from src.dom import wait_network_idle_light, safe_click
from src.phase1 import (SEL_TAB_US_POOL, SEL_TAB_CHANNEL, SEL_SEARCH_BTN,
                        _open_category, SEL_TABLE)


def main() -> None:
    config = load_config()
    pool = config["product_pool"]

    with sync_playwright() as p:
        browser, context = _open_context(p, config, headless=config["app"]["headless"],
                                         storage=ROOT / config["app"]["storage_state"])
        page = context.new_page()

        # 监听 popup（新窗口）
        popups = []
        context.on("page", lambda pg: popups.append(pg.url))

        # 监听网络请求
        requests = []
        page.on("request", lambda rq: requests.append((rq.method, rq.url)))
        page.on("requestfailed", lambda rq: log(f"[diag] ✗ 请求失败: {rq.method} {rq.url} "
                                                f"{rq.failure}"))

        if not is_logged_in(page):
            log("[diag] ✗ 未登录")
            browser.close()
            sys.exit(1)

        page.goto(pool["url"], wait_until="domcontentloaded", timeout=60000)
        wait_network_idle_light(page)
        page.evaluate(
            """(args) => {
                const us = args.us, ch = args.ch;
                const tabs = [...document.querySelectorAll('.el-tabs__item, .el-radio-button, span')];
                const findTab = (txt) => tabs.find(e => {
                    const t=(e.innerText||'').trim();
                    return t===txt && e.getBoundingClientRect().width>0;
                });
                const u = findTab(us); if (u) u.click();
                setTimeout(() => { const c = findTab(ch); if (c) c.click(); }, 800);
            }""",
            {"us": pool["region_tab"], "ch": pool["channel"]},
        )
        page.wait_for_timeout(2000)

        # 品类（用 phase1 的搜索式选中，加多重试）
        for attempt in range(5):
            try:
                _open_category(page, config["category"]["system_path"])
                break
            except RuntimeError as e:
                log(f"[diag] 品类选中失败(第{attempt+1}次): {e}")
                page.keyboard.press("Escape")
                page.wait_for_timeout(1500)
                if attempt == 4:
                    raise
        if pool.get("escape_after_select", True):
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
        safe_click(page, SEL_SEARCH_BTN)
        wait_network_idle_light(page)

        # 勾选第1行
        frozen_rows = page.locator(".vxe-table--fixed-left-wrapper .vxe-table--body-wrapper tr")
        cb_td = frozen_rows.first.locator("td.col--checkbox").first
        if cb_td.count():
            cb_td.click(timeout=8000)
            page.wait_for_timeout(300)

        log(f"[diag] 勾选后 checkbox: "
            f"{page.evaluate('''() => { const tr=document.querySelector('.vxe-table--fixed-left-wrapper .vxe-table--body-wrapper tr'); const i=tr&&tr.querySelector('.vxe-checkbox--icon'); return i?(typeof i.className==='string'?i.className:''):'NO'; }''')}")

        # 清空请求记录，准备捕获「直接加入上架计划」的动作
        requests.clear()
        log(f"[diag] 点击前 URL: {page.url}")

        # 点 trigger 展开下拉
        trig = page.locator("button.el-dropdown-selfdefine").first
        if trig.count():
            trig.click(timeout=8000)
            page.wait_for_timeout(800)

        # 点「直接加入上架计划」
        item = page.locator(".el-dropdown-menu__item:has-text('直接加入上架计划')").first
        if item.count():
            item.click(timeout=8000)
            log("[diag] 已点击「直接加入上架计划」")

        # 等待并观察
        page.wait_for_timeout(6000)
        log(f"[diag] 点击后 URL: {page.url}")
        log(f"[diag] popups 数量: {len(popups)} → {popups}")

        # dump 点击后触发的网络请求（过滤静态资源）
        seen = set()
        for m, u in requests:
            if u in seen:
                continue
            seen.add(u)
            if any(x in u for x in ["/api/", "plan", "publish", "shelf", "listing",
                                     "sku", "join", "add", "warehouse"]):
                log(f"[diag]   请求 {m} {u[:150]}")

        page.screenshot(path=str(ROOT / "runtime" / "diag_after_join_click.png"), full_page=True)

        # dump 页面标题 + 是否出现新容器
        title = page.title()
        log(f"[diag] 页面标题: {title}")
        container = page.evaluate(
            """() => {
                const sels = ['.el-drawer', '.el-dialog', '.el-overlay', '.el-popover',
                    '.el-message-box', '.el-drawer__body', '[class*=drawer]',
                    '.el-drawer__container'];
                for (const s of sels) {
                    const els = [...document.querySelectorAll(s)]
                        .filter(e => e.offsetParent !== null
                            || e.getBoundingClientRect().width > 50);
                    if (els.length) {
                        return {sel: s, n: els.length,
                                txt: (els[0].innerText||'').slice(0,50)};
                    }
                }
                return null;
            }"""
        )
        log(f"[diag] 可见弹层容器: {container}")

        browser.close()


if __name__ == "__main__":
    main()