"""探测：产品池表格行内「加入上架计划」按钮的选择器与下拉菜单结构。

目的：确认单行场景下行内按钮如何定位（可能需横向滚动操作列），以及点击后
弹出的下拉菜单项文本（「直接加入上架计划」/「表格加入上架计划」）。
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
        if not is_logged_in(page):
            log("[diag] ✗ 未登录")
            browser.close()
            sys.exit(1)

        page.goto(pool["url"], wait_until="domcontentloaded", timeout=60000)
        wait_network_idle_light(page)
        safe_click(page, SEL_TAB_US_POOL)
        page.wait_for_timeout(800)
        safe_click(page, SEL_TAB_CHANNEL)
        page.wait_for_timeout(800)
        for attempt in range(3):
            try:
                _open_category(page, config["category"]["system_path"])
                break
            except RuntimeError as e:
                log(f"[diag] 品类选中失败(第{attempt+1}次): {e}")
                page.keyboard.press("Escape")
                page.wait_for_timeout(1000)
        if pool.get("escape_after_select", True):
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
        safe_click(page, SEL_SEARCH_BTN)
        wait_network_idle_light(page)
        try:
            page.wait_for_selector(".vxe-table--body-wrapper tr", timeout=15000)
        except Exception:
            pass
        for _ in range(20):
            page.wait_for_timeout(500)
            if page.locator(SEL_TABLE).first.locator("tr").count() > 0:
                break

        # dump 行内所有按钮（含文本/坐标），确认「加入上架计划」行内按钮
        btns = page.evaluate(
            """() => {
                const rows = [...document.querySelectorAll(
                    '.vxe-table--body-wrapper tr, .vxe-table--fixed-right-wrapper tr')]
                    .filter(r => r.offsetParent !== null);
                if (!rows.length) return 'NO_ROWS';
                const out = [];
                for (let ri = 0; ri < Math.min(rows.length, 3); ri++) {
                    const r = rows[ri];
                    const bs = [...r.querySelectorAll('button')].map((b, bi) => {
                        const r = b.getBoundingClientRect();
                        return { bi, t: (b.innerText || '').trim(),
                                 x: Math.round(r.x), y: Math.round(r.y),
                                 w: Math.round(r.width), cls: b.className };
                    });
                    out.push({ row: ri, buttons: bs });
                }
                return out;
            }"""
        )
        log("[diag] 行内按钮:")
        if isinstance(btns, list):
            for rb in btns:
                log(f"[diag]   row{rb['row']}: {rb['buttons']}")
        else:
            log(f"[diag]   {btns}")

        # 尝试横向滚动固定右侧列，看行内操作按钮是否在 fixed-right 区
        page.evaluate(
            """() => {
                const wrappers = document.querySelectorAll(
                    '.vxe-table--fixed-right-wrapper .vxe-table--body-wrapper');
                wrappers.forEach(w => { w.scrollLeft = w.scrollWidth; });
                const main = document.querySelector('.vxe-table--body-wrapper');
                if (main) main.scrollLeft = main.scrollWidth;
            }"""
        )
        page.wait_for_timeout(800)
        btns2 = page.evaluate(
            """() => {
                const rows = [...document.querySelectorAll(
                    '.vxe-table--body-wrapper tr, .vxe-table--fixed-right-wrapper tr')]
                    .filter(r => r.offsetParent !== null);
                if (!rows.length) return 'NO_ROWS';
                const out = [];
                for (let ri = 0; ri < Math.min(rows.length, 3); ri++) {
                    const r = rows[ri];
                    const bs = [...r.querySelectorAll('button')].map((b, bi) => {
                        const r = b.getBoundingClientRect();
                        return { bi, t: (b.innerText || '').trim(),
                                 x: Math.round(r.x), y: Math.round(r.y) };
                    });
                    out.push({ row: ri, buttons: bs });
                }
                return out;
            }"""
        )
        log("[diag] 滚动后行内按钮:")
        if isinstance(btns2, list):
            for rb in btns2:
                log(f"[diag]   row{rb['row']}: {rb['buttons']}")
        else:
            log(f"[diag]   {btns2}")

        shot = ROOT / "runtime" / "diag_row_join_btn.png"
        page.screenshot(path=str(shot), full_page=True)
        log(f"[diag] 截图: {shot}")

        browser.close()


if __name__ == "__main__":
    main()