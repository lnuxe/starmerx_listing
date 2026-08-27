"""dump 指定行利润抽屉里的列头 colid + title，确认 col_58/col_69 是否稳定。"""
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

        for row_idx in (3, 4):
            ok = _open_profit_drawer(page, row_idx=row_idx)
            page.wait_for_timeout(3000)
            # 点搜索加载数据
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
                    if (btn) { btn.click(); return true; } return false;
                }"""
            )
            for _ in range(15):
                time_out = page.evaluate(
                    """() => {
                        const roots = [...document.querySelectorAll(
                            '.el-drawer:not([style*="display: none"]), '
                            + '.el-dialog:not([style*="display: none"])')]
                            .filter(r => r.offsetParent !== null
                                || r.getBoundingClientRect().width > 0);
                        const root = roots.find(r => (r.innerText||'').includes('保存算价'))
                            || roots[0];
                        if (!root) return true;
                        return root.querySelector('td[colid="col_58"]') !== null;
                    }"""
                )
                if time_out:
                    break
                page.wait_for_timeout(1000)

            # dump 抽屉内所有 th 的 colid + title
            headers = page.evaluate(
                """() => {
                    const roots = [...document.querySelectorAll(
                        '.el-drawer:not([style*="display: none"]), '
                        + '.el-dialog:not([style*="display: none"])')]
                        .filter(r => r.offsetParent !== null
                            || r.getBoundingClientRect().width > 0);
                    const root = roots.find(r => (r.innerText||'').includes('保存算价'))
                        || roots[0];
                    if (!root) return [];
                    const out = [];
                    for (const th of root.querySelectorAll('th')) {
                        out.push({
                            colid: th.getAttribute('colid'),
                            title: (th.innerText||'').trim().replace(/\\n/g,' ').slice(0,30),
                        });
                    }
                    return out;
                }"""
            )
            log(f"SPU#{row_idx} 抽屉列头: {json.dumps(headers, ensure_ascii=False)}")

            # 关闭
            page.keyboard.press("Escape")
            page.wait_for_timeout(1500)

        browser.close()


if __name__ == "__main__":
    main()