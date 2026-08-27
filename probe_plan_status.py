"""勘察上架计划页：dump 主表列头 + 每行刊登状态，找出「未刊登」行的识别方式。"""
from __future__ import annotations

import json
import sys

from playwright.sync_api import sync_playwright

from src.config import load_config, log, ROOT
from src.login import _open_context, is_logged_in
from src.phase2 import _open_plan_page


def main() -> None:
    config = load_config()
    with sync_playwright() as p:
        browser, context = _open_context(
            p, config, headless=False,
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
        page.wait_for_timeout(1500)

        # dump 所有 vxe-table 的列头（固定列和滚动列可能分属两个表）
        tables = page.evaluate(
            """() => {
                const out = [];
                for (const t of document.querySelectorAll('.vxe-table')) {
                    const heads = [...t.querySelectorAll('.vxe-header-column .vxe-cell, .vxe-header-column .vxe-column--title')]
                        .map(h => (h.innerText||'').trim()).filter(Boolean);
                    const colids = [...t.querySelectorAll('th[colid], td[colid]')]
                        .map(c => c.getAttribute('colid')).filter(Boolean);
                    out.push({ heads, colids_sample: colids.slice(0, 30) });
                }
                return out;
            }"""
        )
        log(f"表格列头: {json.dumps(tables, ensure_ascii=False)}")

        # dump 首行每列的文本（含刊登状态）
        row = page.evaluate(
            """() => {
                const body = document.querySelector('.vxe-table--body-wrapper');
                if (!body) return null;
                const tr = body.querySelector('tr');
                if (!tr) return null;
                const cells = [...tr.querySelectorAll('td')].map(td => ({
                    colid: td.getAttribute('colid'),
                    text: (td.innerText||'').trim().slice(0, 60),
                }));
                return cells;
            }"""
        )
        log(f"首行单元格: {json.dumps(row, ensure_ascii=False)}")

        # 截全屏
        png = ROOT / "runtime" / "手动操作轨迹" / "plan_table_full.png"
        page.screenshot(path=str(png), full_page=True)
        log(f"截图: {png}")

        browser.close()


if __name__ == "__main__":
    main()