"""勘察 Phase2 利润测算抽屉（col12）的交互细节——dump 所有可编辑 input 及关键按钮。

重点确认：
  1) 筛选区「公司利润率」输入框（改它触发重新测算）
  2) 表格每行的 公司利润率 / 个人利润率 / 活动营销费 输入框
  3) 「保存算价结果」「重新测算」按钮坐标
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_config, log, ROOT  # noqa: E402
from src.login import _open_context, is_logged_in  # noqa: E402
from src.dom import wait_network_idle_light  # noqa: E402

SEL_MENU_SALES = "text=销售管理"
SEL_SUB_LISTING_PLAN = "text=上架计划"


def main() -> None:
    config = load_config()
    with sync_playwright() as p:
        browser, context = _open_context(p, config, headless=False,
                                         storage=ROOT / config["app"]["storage_state"])
        page = context.new_page()
        page.goto(config["app"]["base_url"], wait_until="domcontentloaded", timeout=60000)
        wait_network_idle_light(page)
        page.wait_for_timeout(2500)
        sidebar = page.locator(".sidebar-container")
        sidebar.locator(SEL_MENU_SALES).first.click(timeout=8000)
        page.wait_for_timeout(1500)
        sidebar.locator(SEL_SUB_LISTING_PLAN).first.click(timeout=8000)
        page.wait_for_timeout(2500)

        # 等待数据行
        for _ in range(20):
            rc = page.evaluate(
                """() => {
                    const t = document.querySelector('.vxe-table');
                    if (!t) return 0;
                    return t.querySelectorAll('.vxe-body--row, .vxe-row, tr.vxe-row')
                        .length;
                }"""
            )
            if rc and rc > 0:
                break
            page.wait_for_timeout(1000)
        log(f"[probe] 表格数据行数: {rc}")

        # 点 col12（价格列）编辑按钮 = 第2个编辑（nth(2)）
        btn = page.locator(".vxe-table button:has-text('编辑')").nth(2)
        btn.click(timeout=8000)
        page.wait_for_timeout(3500)
        log("[probe] 已打开利润测算抽屉")

        # dump 抽屉内所有 input（含 value/placeholder/disabled）和 button
        info = page.evaluate(
            """() => {
                const roots = [...document.querySelectorAll(
                    '.el-drawer:not([style*="display: none"]), '
                    + '.el-dialog:not([style*="display: none"])')]
                    .filter(r => r.offsetParent !== null
                        || r.getBoundingClientRect().width > 0);
                const root = roots.find(r => {
                    const s = (r.innerText||'');
                    return s.includes('利润测算') || s.includes('公司利润率')
                        || s.includes('保存算价');
                }) || roots[0];
                if (!root) return { note: '无可见抽屉' };
                const inputs = [...root.querySelectorAll('input')]
                    .filter(e => e.offsetParent !== null)
                    .map((e, i) => {
                        const r = e.getBoundingClientRect();
                        return { i, val: e.value, ph: e.placeholder,
                                 x: Math.round(r.x), y: Math.round(r.y),
                                 disabled: e.disabled };
                    });
                const buttons = [...root.querySelectorAll('button')]
                    .filter(e => e.offsetParent !== null)
                    .map((e, i) => {
                        const r = e.getBoundingClientRect();
                        return { i, t: (e.innerText||'').trim(),
                                 x: Math.round(r.x), y: Math.round(r.y) };
                    });
                const title = (root.querySelector(
                    '.el-drawer__title, .el-dialog__title')||{}).innerText||'';
                return { title, inputs, buttons };
            }"""
        )
        log(f"[probe] 利润测算抽屉结构:")
        log(f"[probe]   标题: {info.get('title')}")
        log(f"[probe]   输入框({len(info.get('inputs', []))}):")
        for inp in info.get("inputs", []):
            log(f"[probe]     input[{inp['i']}] val={inp['val']!r} ph={inp['ph']!r} "
                f"@({inp['x']},{inp['y']}) disabled={inp['disabled']}")
        log(f"[probe]   按钮({len(info.get('buttons', []))}):")
        for b in info.get("buttons", []):
            log(f"[probe]     btn[{b['i']}] {b['t']!r} @({b['x']},{b['y']})")

        shot = ROOT / "runtime" / "profit_calc_detail.png"
        page.screenshot(path=str(shot), full_page=True)
        log(f"[probe] 截图: {shot}")

        browser.close()


if __name__ == "__main__":
    main()