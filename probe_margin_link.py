"""精确读取 col_58 利润列 公司/个人 两行的金额和利润率。"""
from __future__ import annotations

import json
import sys

from playwright.sync_api import sync_playwright

from src.config import load_config, log, ROOT
from src.login import _open_context, is_logged_in
from src.phase2 import _open_plan_page, _open_profit_drawer, _snap_row0, _recalc_profit


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
        for _ in range(25):
            if _snap_row0(page).get("margin") is not None:
                break
            page.wait_for_timeout(1000)

        # 精确 dump col_58 完整结构：公司行、个人行各自的金额和百分比
        def dump_col58():
            return page.evaluate(
                """() => {
                    const roots = [...document.querySelectorAll(
                        '.el-drawer:not([style*="display: none"]), '
                        + '.el-dialog:not([style*="display: none"])')]
                        .filter(r => r.offsetParent !== null
                            || r.getBoundingClientRect().width > 0);
                    const root = roots.find(r => (r.innerText||'').includes('保存算价'))
                        || roots[0];
                    const td = root.querySelector('td[colid="col_58"]');
                    if (!td) return { note: 'no td' };
                    // 两个 flex-box：第一个是公司，第二个是个人
                    const flexes = [...td.querySelectorAll('.flex-box')];
                    const res = [];
                    for (const f of flexes) {
                        const span = f.querySelector('span');
                        const input = f.querySelector('input');
                        const pct = f.querySelector('.column-right-flex-box span');
                        const prog = f.querySelector('[role=progressbar]');
                        res.push({
                            label: span ? span.innerText.trim() : '',
                            amount: span ? span.innerText.trim() : '',
                            input_value: input ? input.value : null,
                            pct_text: pct ? pct.innerText.trim() : null,
                            progress: prog ? prog.getAttribute('aria-valuenow') : null,
                        });
                    }
                    return { res, full_text: td.innerText };
                }"""
            )

        log(f"初始 col_58: {json.dumps(dump_col58(), ensure_ascii=False)}")

        # 试几个公司利润率，观察公司/个人两行的变化
        for m in [40, 20, 10, 5, 4, 3]:
            page.fill("#__margin2__", f"{m:.2f}")
            page.keyboard.press("Enter")
            page.wait_for_timeout(300)
            _recalc_profit(page)
            page.wait_for_timeout(800)
            d = dump_col58()
            log(f"公司利润率={m}% → {json.dumps(d, ensure_ascii=False)}")

        browser.close()


if __name__ == "__main__":
    main()