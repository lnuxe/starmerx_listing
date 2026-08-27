"""精确勘察：右侧滚动列的列头 + 多行状态，定位「刊登状态」列。"""
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

        # 精确 dump 所有 header 列的 colid + title
        headers = page.evaluate(
            """() => {
                const out = [];
                for (const t of document.querySelectorAll('.vxe-table')) {
                    const hdr = t.querySelector('.vxe-table--header');
                    if (!hdr) continue;
                    const cols = [...hdr.querySelectorAll('th')].map(th => ({
                        colid: th.getAttribute('colid'),
                        title: (th.innerText||'').trim().replace(/\\n/g,' ').slice(0,40),
                    }));
                    out.push(cols);
                }
                return out;
            }"""
        )
        log(f"列头(colid+title): {json.dumps(headers, ensure_ascii=False)}")

        # dump 前 5 行的 col_24/col_25/col_26 等右侧列
        rows = page.evaluate(
            """() => {
                const bodies = [...document.querySelectorAll('.vxe-table--body-wrapper')];
                // 找包含行最多的 body
                let body = bodies.sort((a,b) => b.querySelectorAll('tr').length - a.querySelectorAll('tr').length)[0];
                if (!body) return [];
                const trs = [...body.querySelectorAll('tr')].slice(0, 5);
                return trs.map(tr => {
                    const cells = {};
                    for (const td of tr.querySelectorAll('td')) {
                        const cid = td.getAttribute('colid');
                        if (cid && ['col_22','col_23','col_24','col_25','col_26'].includes(cid)) {
                            cells[cid] = (td.innerText||'').trim().replace(/\\n/g,' ').slice(0,40);
                        }
                    }
                    return cells;
                });
            }"""
        )
        log(f"前5行右侧列: {json.dumps(rows, ensure_ascii=False)}")

        browser.close()


if __name__ == "__main__":
    main()