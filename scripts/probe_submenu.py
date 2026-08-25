"""勘察「销售管理」一级菜单下的子菜单结构，找上架计划/上架计划页入口。"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from src.config import load_config, log, ROOT
from src.login import _open_context, is_logged_in
from src.dom import wait_network_idle_light

RE_HASH = re.compile(r"#.*")


def main() -> None:
    config = load_config()
    with sync_playwright() as p:
        browser, context = _open_context(p, config, headless=True,
                                         storage=ROOT / config["app"]["storage_state"])
        page = context.new_page()
        page.goto(config["product_pool"]["url"], wait_until="domcontentloaded", timeout=60000)
        wait_network_idle_light(page)
        page.wait_for_timeout(2500)
        log(f"[probe] URL: {page.url}")
        if not is_logged_in(page):
            log("[probe] ✗ 未登录")
            browser.close()
            return

        # 左侧一级菜单「销售管理」，点击展开子菜单
        sm = page.locator("li:has-text('销售管理'), .el-sub-menu:has-text('销售管理')").first
        if not sm.count():
            log("[probe] ✗ 未找到「销售管理」菜单")
            browser.close()
            return
        sm.click(timeout=8000)
        page.wait_for_timeout(1500)
        log("[probe] 已点击「销售管理」")

        # dump 展开后的子菜单项
        out = page.evaluate(
            """() => {
                const out = [];
                const seen = new Set();
                document.querySelectorAll('.el-menu li, .el-menu .el-menu-item, .el-menu a').forEach((m) => {
                    const txt = (m.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 40);
                    if (!txt || seen.has(txt)) return;
                    const r = m.getBoundingClientRect();
                    if (r.width === 0 && r.height === 0) return;
                    seen.add(txt);
                    const href = m.closest('a') ? m.closest('a').getAttribute('href') : '';
                    const cls = (m.className || '').split(' ')[0];
                    out.push(`<${m.tagName.toLowerCase()}>.${cls} "${txt}" href=${href || '-'}`);
                });
                return out.join('\\n');
            }"""
        )
        runtime = ROOT / "runtime"
        dump = runtime / "probe_submenu.txt"
        dump.write_text(out, encoding="utf-8")
        log(f"[probe] 子菜单清单已保存: {dump}")
        shot = runtime / "probe_submenu.png"
        page.screenshot(path=str(shot), full_page=True)
        log(f"[probe] 截图: {shot}")
        browser.close()


if __name__ == "__main__":
    main()