"""探测3：点击第一行行内「加入上架计划」按钮，观察弹出的是下拉菜单还是 dialog。"""
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
            log("[diag3] ✗ 未登录")
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
                log(f"[diag3] 品类选中失败(第{attempt+1}次): {e}")
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

        # 获取所有行内「加入上架计划」按钮坐标（span 文本）
        pts = page.evaluate(
            """() => {
                const spans = [...document.querySelectorAll('span')]
                    .filter(s => (s.innerText || '').trim() === '加入上架计划'
                              && s.offsetParent !== null);
                const out = [];
                for (const s of spans) {
                    const r = s.getBoundingClientRect();
                    // 排除顶部批量按钮：找它在表格行内的祖先
                    const inRow = !!s.closest('tr');
                    out.push({ x: Math.round(r.x + r.width / 2),
                               y: Math.round(r.y + r.height / 2),
                               inRow });
                }
                return out;
            }"""
        )
        row_btns = [p for p in pts if p["inRow"]] if isinstance(pts, list) else []
        log(f"[diag3] 行内「加入上架计划」按钮数: {len(row_btns)}")
        for p in row_btns[:5]:
            log(f"[diag3]   @({p['x']},{p['y']})")

        if not row_btns:
            log("[diag3] ✗ 无行内按钮")
            browser.close()
            sys.exit(1)

        # 点击第一行行内按钮
        target = row_btns[0]
        log(f"[diag3] 点击行内按钮 @({target['x']},{target['y']})")
        page.mouse.click(target["x"], target["y"])
        page.wait_for_timeout(1200)

        # 观察弹出的元素
        menu = page.evaluate(
            """() => {
                const menuItems = [...document.querySelectorAll('.el-dropdown-menu__item')]
                    .map(m => (m.innerText || '').trim()).filter(Boolean);
                const dialogs = [...document.querySelectorAll('.el-dialog')]
                    .filter(d => d.offsetParent !== null || d.getBoundingClientRect().width > 100)
                    .map(d => d.getAttribute('aria-label') || (d.innerText || '').slice(0, 30));
                const tooltips = [...document.querySelectorAll('.el-popper, .el-dropdown-menu')]
                    .filter(t => t.offsetParent !== null)
                    .map(t => (t.innerText || '').trim().slice(0, 50));
                return { menuItems, dialogs, tooltips };
            }"""
        )
        log(f"[diag3] 点击后状态: {menu}")

        shot = ROOT / "runtime" / "diag_row_join_click.png"
        page.screenshot(path=str(shot))
        log(f"[diag3] 截图: {shot}")

        browser.close()


if __name__ == "__main__":
    main()