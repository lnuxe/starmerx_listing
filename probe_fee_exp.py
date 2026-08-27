"""临时探针：验证活动营销费 input 填「金额」还是「占比」。

实验：读当前 col_69 值 → 改成 50 → 点重新测算 → 读回 col_69 的 span 占比% 与 input 值。
"""
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
        page.wait_for_timeout(5000)

        s0 = _snap_row0(page)
        log(f"改前: {json.dumps(s0, ensure_ascii=False)}")

        # 改成 50（可能是占比，也可能是金额，先试 50）
        page.fill("#__mkt_fee__", "50")
        page.keyboard.press("Enter")
        page.wait_for_timeout(500)

        _recalc_profit(page)
        page.wait_for_timeout(1000)

        s1 = _snap_row0(page)
        log(f"改后(填50): {json.dumps(s1, ensure_ascii=False)}")

        # 精读 col_69 完整结构
        detail = page.evaluate(
            """() => {
                const roots = [...document.querySelectorAll(
                    '.el-drawer:not([style*="display: none"]), '
                    + '.el-dialog:not([style*="display: none"])')]
                    .filter(r => r.offsetParent !== null
                        || r.getBoundingClientRect().width > 0);
                const root = roots.find(r => (r.innerText||'').includes('保存算价'))
                    || roots[0];
                const td = root.querySelector('td[colid="col_69"]');
                if (!td) return 'no td';
                return {
                    text: td.innerText,
                    input_value: td.querySelector('input')?.value,
                    progress_aria: td.querySelector('[role=progressbar]')?.getAttribute('aria-valuenow'),
                };
            }"""
        )
        log(f"col_69 详情: {json.dumps(detail, ensure_ascii=False)}")

        shot = ROOT / "runtime" / "probe_fee_experiment.png"
        page.screenshot(path=str(shot), full_page=True)
        log(f"截图: {shot}")
        browser.close()


if __name__ == "__main__":
    main()