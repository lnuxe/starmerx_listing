"""临时探针：dump 上架计划列表页完整列头（含横向滚动区），定位「活动营销费」列。"""
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
            p, config, headless=config["app"]["headless"],
            storage=ROOT / config["app"]["storage_state"],
        )
        page = context.new_page()
        if not is_logged_in(page):
            log("✗ 未登录"); browser.close(); sys.exit(1)

        _open_plan_page(page, config)
        page.wait_for_timeout(2000)

        # 等待数据行
        try:
            page.locator(".vxe-table--body-wrapper tr").first.wait_for(
                state="attached", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(1500)

        # dump 所有 vxe-table 列头 + 首行单元格文本
        dump = page.evaluate(
            """() => {
                const out = [];
                for (const tb of document.querySelectorAll('.vxe-table')) {
                    const heads = [...tb.querySelectorAll(
                        '.vxe-header-column .vxe-cell, th')]
                        .map(h => (h.innerText||'').trim()).filter(Boolean);
                    const rows = [...tb.querySelectorAll(
                        '.vxe-body--row, tr.vxe-row, tbody tr')]
                        .filter(r => r.offsetParent !== null);
                    const t = { heads, row_count: rows.length };
                    if (rows.length) {
                        t.first_row_text = rows[0].innerText;
                        t.first_row_inputs = [...rows[0].querySelectorAll('input')]
                            .map(e => ({ value: e.value, ph: e.placeholder||'' }));
                    }
                    out.push(t);
                }
                return out;
            }"""
        )
        log(json.dumps(dump, ensure_ascii=False, indent=2))

        shot = ROOT / "runtime" / "probe_plan_list.png"
        page.screenshot(path=str(shot), full_page=True)
        log(f"截图: {shot}")
        browser.close()


if __name__ == "__main__":
    main()