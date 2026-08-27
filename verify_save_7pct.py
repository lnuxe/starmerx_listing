"""验证：公司利润率设为7%（个人5.04%）后，点「保存算价结果」是否触发拦截。

用正确方法（fill+blur）设置，然后点保存，观察弹窗。
"""
from __future__ import annotations

import json
import sys

from playwright.sync_api import sync_playwright

from src.config import load_config, log, ROOT
from src.login import _open_context, is_logged_in
from src.phase2 import (_open_plan_page, _open_profit_drawer, _snap_row0,
                        _set_company_margin, _set_activity_marketing_rate,
                        _recalc_profit)

SHOT_DIR = ROOT / "runtime" / "手动操作轨迹"


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
        page.wait_for_timeout(1000)

        _open_profit_drawer(page, row_idx=0)
        page.wait_for_timeout(2000)

        # 点搜索加载测算行
        page.evaluate(
            """() => {
                const roots = [...document.querySelectorAll(
                    '.el-drawer:not([style*="display: none"]), '
                    + '.el-dialog:not([style*="display: none"])')]
                    .filter(r => r.offsetParent !== null
                        || r.getBoundingClientRect().width > 0);
                const root = roots.find(r => (r.innerText||'').includes('保存算价'))
                    || roots[0];
                const btn = [...root.querySelectorAll('button')]
                    .find(b => (b.innerText||'').trim() === '搜索');
                if (btn) { btn.click(); return true; } return false;
            }"""
        )
        for _ in range(25):
            if _snap_row0(page).get("margin") is not None:
                break
            page.wait_for_timeout(1000)

        # 设活动营销费 50%
        _set_activity_marketing_rate(page, 50.0)
        _recalc_profit(page)
        page.wait_for_timeout(800)

        # 设公司利润率 7%（个人应≈5.04%）
        _set_company_margin(page, 7.0)
        _recalc_profit(page)
        page.wait_for_timeout(1000)
        s = _snap_row0(page)
        log(f"设公司利润率7%后: margin={s.get('margin')} personal={s.get('personal_pct')}%")
        page.screenshot(path=str(SHOT_DIR / "verify_7pct_before_save.png"), full_page=True)

        # 点「保存算价结果」
        try:
            page.get_by_role("button", name="保存算价结果").click(timeout=5000)
            page.wait_for_timeout(2500)
            log("✓ 已点击保存算价结果")
        except Exception as e:
            log(f"✗ 点击保存失败: {e}")

        # 检测是否弹出「价格校验异常」弹窗
        dialogs = page.evaluate(
            """() => {
                const ds = [...document.querySelectorAll(
                    '.el-dialog:not([style*="display: none"]), .el-message-box')]
                    .filter(d => d.offsetParent !== null
                        || d.getBoundingClientRect().width > 0);
                return ds.map(d => {
                    const t = d.querySelector('.el-dialog__title, .el-message-box__title');
                    const ta = d.querySelector('textarea');
                    const btns = [...d.querySelectorAll('button')].map(b => (b.innerText||'').trim()).filter(Boolean);
                    return { title: t ? t.innerText.trim() : '', has_textarea: !!ta, buttons: btns, text: (d.innerText||'').slice(0,500) };
                });
            }"""
        )
        log(f"保存后弹窗: {json.dumps(dialogs, ensure_ascii=False)}")
        page.screenshot(path=str(SHOT_DIR / "verify_after_save.png"), full_page=True)

        browser.close()


if __name__ == "__main__":
    main()