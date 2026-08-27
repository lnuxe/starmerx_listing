"""临时探针：打开利润测算抽屉，dump 精确列头 + 首行所有 input 的位置/值/placeholder。

用于修正 phase2._snap_row0 / _JS_HAS_MAIN_TABLE 的列头与输入框索引假设。
"""
from __future__ import annotations

import json
import sys

from playwright.sync_api import sync_playwright

from src.config import load_config, log, ROOT
from src.login import _open_context, is_logged_in
from src.dom import wait_network_idle_light
from src.phase2 import _open_plan_page, _open_profit_drawer


def main() -> None:
    config = load_config()
    with sync_playwright() as p:
        browser, context = _open_context(
            p, config, headless=config["app"]["headless"],
            storage=ROOT / config["app"]["storage_state"],
        )
        page = context.new_page()
        if not is_logged_in(page):
            log("✗ 未登录"); browser.close(); sys.exit(1)

        _open_plan_page(page, config)

        # 等待列表渲染
        page.wait_for_timeout(2000)
        table = page.locator(".vxe-table--body-wrapper").first
        try:
            table.locator("tr").first.wait_for(state="attached", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(1000)

        # 打开首行利润抽屉
        ok = _open_profit_drawer(page, row_idx=0)
        log(f"打开抽屉: {ok}")
        page.wait_for_timeout(1500)

        # 点「搜索」加载该 SPU 测算行
        page.evaluate(
            """() => {
                const roots = [...document.querySelectorAll(
                    '.el-drawer:not([style*="display: none"]), '
                    + '.el-dialog:not([style*="display: none"])')]
                    .filter(r => r.offsetParent !== null
                        || r.getBoundingClientRect().width > 0);
                const root = roots.find(r => (r.innerText||'').includes('保存算价'))
                    || roots[0];
                if (!root) return false;
                const btn = [...root.querySelectorAll('button')]
                    .find(b => (b.innerText||'').trim() === '搜索');
                if (!btn) return false;
                btn.click(); return true;
            }"""
        )
        for _ in range(20):
            page.wait_for_timeout(1000)
            n = page.evaluate(
                """() => {
                    const roots = [...document.querySelectorAll(
                        '.el-drawer:not([style*="display: none"]), '
                        + '.el-dialog:not([style*="display: none"])')]
                        .filter(r => r.offsetParent !== null
                            || r.getBoundingClientRect().width > 0);
                    const root = roots.find(r => (r.innerText||'').includes('保存算价'))
                        || roots[0];
                    if (!root) return 0;
                    return root.querySelectorAll('.vxe-body--row, tr.vxe-row, tbody tr').length;
                }"""
            )
            if n > 0:
                break

        # dump 抽屉内所有 vxe-table 的精确列头（含空格，repr 输出）
        dump = page.evaluate(
            """() => {
                const roots = [...document.querySelectorAll(
                    '.el-drawer:not([style*="display: none"]), '
                    + '.el-dialog:not([style*="display: none"])')]
                    .filter(r => r.offsetParent !== null
                        || r.getBoundingClientRect().width > 0);
                const root = roots.find(r => (r.innerText||'').includes('保存算价'))
                    || roots[0];
                if (!root) return { note: 'no root' };
                const out = { tables: [] };
                for (const tb of root.querySelectorAll('.vxe-table, table')) {
                    const heads = [...tb.querySelectorAll(
                        '.vxe-header-column .vxe-cell, th')]
                        .map(h => (h.innerText||'').trim()).filter(Boolean);
                    const rows = [...tb.querySelectorAll(
                        '.vxe-body--row, tr.vxe-row, tbody tr')]
                        .filter(r => r.offsetParent !== null);
                    const t = { heads, row_count: rows.length, first_row: null };
                    if (rows.length) {
                        const r = rows[0];
                        const inputs = [...r.querySelectorAll('input')]
                            .map((e, i) => ({
                                i, value: e.value,
                                placeholder: e.placeholder || '',
                                type: e.type || '',
                                visible: e.offsetParent !== null,
                            }));
                        t.first_row = {
                            text: r.innerText,
                            inputs,
                        };
                    }
                    out.tables.push(t);
                }
                return out;
            }"""
        )
        log("=== 抽屉 dump ===")
        log(json.dumps(dump, ensure_ascii=False, indent=2))

        shot = ROOT / "runtime" / "probe_drawer_dump.png"
        page.screenshot(path=str(shot), full_page=True)
        log(f"截图: {shot}")

        browser.close()


if __name__ == "__main__":
    main()