"""勘察 Phase2 上架计划页结构。

用法: .venv/bin/python -m scripts.probe_phase2
勘察「上架计划」页的表格、行内操作（图片编辑/价格）、批量上架入口。
导航路径：销售管理 → 上架计划
"""
from __future__ import annotations

import re
from pathlib import Path

from playwright.sync_api import sync_playwright

from src.config import load_config, log, ROOT
from src.login import _open_context, is_logged_in
from src.dom import wait_network_idle_light

RE_HASH = re.compile(r"#.*")

SEL_MENU_SALES = "text=销售管理"          # 一级菜单（含子菜单容器）
SEL_SUB_LISTING_PLAN = ".el-menu li:has-text('上架计划')"  # 子菜单项
SEL_PLAN_TABLE = ".vxe-table--body-wrapper"
SEL_SEARCH_BTN = "button:has-text('搜索')"


def log_probe(msg: str) -> None:
    log(f"[probe] {msg}")


def main() -> None:
    config = load_config()
    with sync_playwright() as p:
        browser, context = _open_context(p, config, headless=True,
                                         storage=ROOT / config["app"]["storage_state"])
        page = context.new_page()
        page.goto(config["app"]["base_url"], wait_until="domcontentloaded", timeout=60000)
        wait_network_idle_light(page)
        page.wait_for_timeout(2500)
        log_probe(f"URL: {page.url}")
        if not is_logged_in(page):
            log_probe("✗ 未登录")
            browser.close()
            return

        # 1) 点击侧边栏「销售管理」展开子菜单
        sm = page.locator(".sidebar-container").locator("text=销售管理").first
        if sm.count():
            sm.click(timeout=8000)
            page.wait_for_timeout(1500)
            log_probe("已点击「销售管理」")
            # dump 侧边栏当前所有可见文字，确认子菜单展开
            txts = page.locator(".sidebar-container").evaluate(
                """(el) => [...el.querySelectorAll('li, a, span')]
                    .map(m => (m.innerText||'').trim().replace(/\\s+/g,' ').slice(0,30))
                    .filter(Boolean)"""
            )
            log_probe(f"侧边栏文字: {txts[:40]}")
        else:
            log_probe("✗ 未找到侧边栏「销售管理」")
            browser.close()
            return

        # 2) 点击「上架计划」子菜单
        sub = page.locator(".sidebar-container").locator("text=上架计划").first
        if sub.count():
            sub.click(timeout=8000)
            page.wait_for_timeout(2500)
            log_probe(f"已点击「上架计划」，URL: {page.url}")
        else:
            log_probe("✗ 未找到「上架计划」子菜单")
            browser.close()
            return

        # 3) 勘察页面结构
        checks = {
            "table_上架计划": SEL_PLAN_TABLE,
            "btn_搜索": SEL_SEARCH_BTN,
        }
        for name, sel in checks.items():
            try:
                n = page.locator(sel).count()
                log_probe(f"{'✓' if n else '✗'} {name}: {sel} → {n}")
            except Exception as e:
                log_probe(f"✗ {name}: {e}")

        # dump 表格列头
        headers = page.evaluate(
            """() => {
                const t = document.querySelector('.vxe-table');
                if (!t) return [];
                const cols = t.querySelectorAll('.vxe-header-column .vxe-cell, '
                    + '.vxe-header-column .vxe-column--title');
                return [...cols].map(c => (c.innerText||'').trim()).filter(Boolean);
            }"""
        )
        log_probe(f"表格列头: {headers}")

        # dump 表格行内操作按钮
        btns = page.evaluate(
            """() => {
                const out = [];
                document.querySelectorAll('.vxe-table--body button').forEach((b) => {
                    const t = (b.innerText||'').trim().replace(/\\s+/g,' ').slice(0,20);
                    if (t) out.push(t);
                });
                return [...new Set(out)];
            }"""
        )
        log_probe(f"行内按钮: {btns}")

        shot = ROOT / "runtime" / "probe_phase2.png"
        page.screenshot(path=str(shot), full_page=True)
        log_probe(f"截图: {shot}")
        browser.close()


if __name__ == "__main__":
    main()