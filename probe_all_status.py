"""dump 全部行的 col_25 上架状态，找出「已刊登」和「草稿」行的分布。"""
from __future__ import annotations

import json
import sys
from collections import Counter

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

        rows = page.evaluate(
            """() => {
                const bodies = [...document.querySelectorAll('.vxe-table--body-wrapper')];
                let body = bodies.sort((a,b) => b.querySelectorAll('tr').length - a.querySelectorAll('tr').length)[0];
                if (!body) return [];
                const trs = [...body.querySelectorAll('tr')];
                return trs.map((tr, i) => {
                    const c = {};
                    for (const td of tr.querySelectorAll('td')) {
                        const cid = td.getAttribute('colid');
                        if (cid && ['col_13','col_14','col_22','col_25'].includes(cid)) {
                            c[cid] = (td.innerText||'').trim().replace(/\\n/g,' ').slice(0,40);
                        }
                    }
                    return { idx: i, ...c };
                });
            }"""
        )
        log(f"总行数: {len(rows)}")
        for r in rows:
            log(f"  [{r['idx']}] SPU={r.get('col_13')} SKU={r.get('col_14')} 品类={r.get('col_22')} 上架状态={r.get('col_25')}")

        # 统计状态分布
        statuses = Counter(r.get('col_25', '?') for r in rows)
        log(f"状态分布: {dict(statuses)}")

        browser.close()


if __name__ == "__main__":
    main()