"""临时探针：用「列头文本 → 列 index → 该列 cell input」精确定位各字段。"""
from __future__ import annotations

import json
import sys

from playwright.sync_api import sync_playwright

from src.config import load_config, log, ROOT
from src.login import _open_context, is_logged_in
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
        page.wait_for_timeout(2000)
        try:
            page.locator(".vxe-table--body-wrapper tr").first.wait_for(
                state="attached", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(1000)

        _open_profit_drawer(page, row_idx=0)
        page.wait_for_timeout(1500)

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
            page.evaluate(
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
            # 简单等待后跳出
            break

        # 用列头精确定位：找到滚动表，按列头 index 读该列首行 cell 的 input
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

                // 找含「活动营销费」的滚动表
                let tb = null;
                for (const t of root.querySelectorAll('.vxe-table')) {
                    const hs = [...t.querySelectorAll('.vxe-header-column .vxe-cell, th')]
                        .map(h => (h.innerText||'').trim()).filter(Boolean);
                    if (hs.includes('活动营销费($) / 占比')) { tb = t; break; }
                }
                if (!tb) return { note: 'no scroll table' };

                const headers = [...tb.querySelectorAll('.vxe-header-column .vxe-cell, th')]
                    .map(h => (h.innerText||'').trim()).filter(Boolean);

                // 首行数据（vxe 滚动表里可能有多个 body row，取第一个有 input 的）
                const rows = [...tb.querySelectorAll('.vxe-body--row, tr.vxe-row, tbody tr')]
                    .filter(r => r.offsetParent !== null);
                const row = rows[0];
                if (!row) return { note: 'no row' };

                // 关键：vxe 用 colid/field 关联，读每个 th 的 data-colid 与 td 的对应
                const ths = [...tb.querySelectorAll('.vxe-header-column')];
                const colids = ths.map(th => {
                    const c = th.querySelector('.vxe-cell');
                    return {
                        colid: th.getAttribute('colid') || th.getAttribute('data-colid') || '',
                        field: th.getAttribute('data-field') || '',
                        title: (c ? c.innerText : th.innerText || '').trim(),
                    };
                });

                // 读首行所有 td 的 data-colid / 对应 input
                const tds = [...row.querySelectorAll('td')];
                const cells = tds.map(td => ({
                    colid: td.getAttribute('colid') || td.getAttribute('data-colid') || '',
                    text: (td.innerText||'').trim(),
                    input: (() => { const i = td.querySelector('input'); return i ? i.value : null; })(),
                }));

                return { headers, colids, cells, row_count: rows.length };
            }"""
        )
        log(json.dumps(dump, ensure_ascii=False, indent=2))

        shot = ROOT / "runtime" / "probe_colid.png"
        page.screenshot(path=str(shot), full_page=True)
        log(f"截图: {shot}")
        browser.close()


if __name__ == "__main__":
    main()