"""验证：vxe input 提交机制——fill 后是否需要 blur/Enter/点击别处才能生效。"""
from __future__ import annotations

import json
import sys

from playwright.sync_api import sync_playwright

from src.config import load_config, log, ROOT
from src.login import _open_context, is_logged_in
from src.phase2 import _open_plan_page, _open_profit_drawer, _snap_row0, _recalc_profit


def dump_col58(page):
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
            const flexes = [...td.querySelectorAll('.flex-box')];
            const res = [];
            for (const f of flexes) {
                const input = f.querySelector('input');
                const prog = f.querySelector('[role=progressbar]');
                const pct = f.querySelector('.column-right-flex-box span');
                res.push({
                    input_value: input ? input.value : null,
                    progress: prog ? prog.getAttribute('aria-valuenow') : null,
                    pct_text: pct ? pct.innerText.trim() : null,
                });
            }
            return res;
        }"""
    )


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

        log(f"初始: {json.dumps(dump_col58(page), ensure_ascii=False)}")

        # 方法A：fill + blur（点击页面空白处）
        log("--- 方法A: fill 20 → blur(点空白) → 重新测算 ---")
        page.fill("#__margin2__", "20")
        page.locator("body").click(position={"x": 5, "y": 5})  # blur
        page.wait_for_timeout(500)
        _recalc_profit(page)
        page.wait_for_timeout(1000)
        log(f"结果: {json.dumps(dump_col58(page), ensure_ascii=False)}")

        # 方法B：fill + press Enter + blur
        log("--- 方法B: fill 10 → Enter → blur → 重新测算 ---")
        page.fill("#__margin2__", "10")
        page.keyboard.press("Enter")
        page.wait_for_timeout(300)
        page.locator("body").click(position={"x": 5, "y": 5})
        page.wait_for_timeout(500)
        _recalc_profit(page)
        page.wait_for_timeout(1000)
        log(f"结果: {json.dumps(dump_col58(page), ensure_ascii=False)}")

        # 方法C：fill + press Tab
        log("--- 方法C: fill 5 → Tab → 重新测算 ---")
        page.fill("#__margin2__", "5")
        page.keyboard.press("Tab")
        page.wait_for_timeout(500)
        _recalc_profit(page)
        page.wait_for_timeout(1000)
        log(f"结果: {json.dumps(dump_col58(page), ensure_ascii=False)}")

        browser.close()


if __name__ == "__main__":
    main()