"""勘察利润测算抽屉「活动营销费」列的编辑方式。

目标确认：
  1) 主表每行「活动营销费($) / 占比」列：单元格内有几个 input？各自语义（$金额 / 占比）？
  2) 抽屉筛选区是否有「活动营销费占比」输入框（可批量设置 50%）？
  3) 往哪个 input 填 50 能达成「占比 50%」（而不是 $ 金额 50）。
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
                    return t.querySelectorAll('.vxe-body--row, .vxe-row, tr.vxe-row').length;
                }"""
            )
            if rc and rc > 0:
                break
            page.wait_for_timeout(1000)
        log(f"[probe] 表格数据行数: {rc}")

        # 点 col12（价格列）编辑按钮 = 第2个编辑（nth(2)）→ 利润测算抽屉
        page.locator(".vxe-table button:has-text('编辑')").nth(2).click(timeout=8000)
        # 轮询等待抽屉真正渲染出「保存算价」按钮（内部表格异步加载）
        loaded = False
        for _ in range(30):
            has = page.evaluate(
                """() => {
                    const roots = [...document.querySelectorAll(
                        '.el-drawer:not([style*="display: none"]), '
                        + '.el-dialog:not([style*="display: none"])')]
                        .filter(r => r.offsetParent !== null
                            || r.getBoundingClientRect().width > 0);
                    const root = roots.find(r => {
                        const s = (r.innerText||'');
                        return s.includes('利润测算') || s.includes('保存算价');
                    }) || roots[0];
                    if (!root) return false;
                    return (root.innerText||'').includes('保存算价');
                }"""
            )
            if has:
                loaded = True
                break
            page.wait_for_timeout(1000)
        log(f"[probe] 已打开利润测算抽屉, 内容加载: {'✓' if loaded else '✗'}")
        page.wait_for_timeout(1000)

        # 1) 读取主表当前行（首行）文本（了解 SPU/SKU 结构）
        first_sku = ""
        try:
            first_sku = page.evaluate(
                """() => {
                    const row = document.querySelector('.vxe-table .vxe-body--row, '
                        + '.vxe-table tr.vxe-row');
                    if (!row) return '';
                    return row.innerText.slice(0, 120);
                }"""
            )
        except Exception:
            pass
        log(f"[probe] 主表首行文本: {first_sku!r}")

        page.wait_for_timeout(2000)

        # 1.5) 点抽屉内「搜索」按钮强制加载测算数据（不填筛选，全量）
        try:
            page.get_by_role("button", name="搜索").first.click(timeout=5000)
            # 等待抽屉主表出现数据行（vxe-input y>500 且非筛选区）
            for _ in range(25):
                has_data = page.evaluate(
                    """() => {
                        const roots = [...document.querySelectorAll(
                            '.el-drawer:not([style*="display: none"]), '
                            + '.el-dialog:not([style*="display: none"])')]
                            .filter(r => r.getBoundingClientRect().width > 0);
                        const root = roots.find(r => (r.innerText||'').includes('保存算价'))
                            || roots[0];
                        if (!root) return false;
                        return [...root.querySelectorAll('.vxe-input--inner')]
                            .some(e => e.getBoundingClientRect().y > 500);
                    }"""
                )
                if has_data:
                    break
                page.wait_for_timeout(1000)
            log(f"[probe] 已点搜索，测算数据加载: {'✓' if has_data else '✗'}")
        except Exception as e:
            log(f"[probe] 点搜索失败: {e}")
        page.wait_for_timeout(1500)

        # 1) 定位抽屉根
        root_info = page.evaluate(
            """() => {
                const roots = [...document.querySelectorAll(
                    '.el-drawer:not([style*="display: none"]), '
                    + '.el-dialog:not([style*="display: none"])')]
                    .filter(r => r.offsetParent !== null
                        || r.getBoundingClientRect().width > 0);
                const root = roots.find(r => {
                    const s = (r.innerText||'');
                    return s.includes('利润测算') || s.includes('保存算价');
                }) || roots[0];
                if (!root) return { note: '无抽屉' };
                return { found: true };
            }"""
        )
        log(f"[probe] 抽屉根: {root_info}")

        # 2) dump 抽屉内所有 input（全量，含筛选区+表格区）
        info = page.evaluate(
            """() => {
                const roots = [...document.querySelectorAll(
                    '.el-drawer:not([style*="display: none"]), '
                    + '.el-dialog:not([style*="display: none"])')]
                    .filter(r => r.offsetParent !== null
                        || r.getBoundingClientRect().width > 0);
                const root = roots.find(r => {
                    const s = (r.innerText||'');
                    return s.includes('利润测算') || s.includes('保存算价');
                }) || roots[0];
                if (!root) return { note: '无抽屉' };
                const out = [];
                [...root.querySelectorAll('input')].forEach((e, i) => {
                    const r = e.getBoundingClientRect();
                    if (r.width === 0) return;
                    out.push({ i, val: e.value, ph: e.placeholder,
                               x: Math.round(r.x), y: Math.round(r.y),
                               cls: (e.className||'').slice(0,40) });
                });
                return out;
            }"""
        )
        log(f"[probe] 抽屉内全部可见 input ({len(info)}):")
        for inp in info:
            log(f"[probe]   input[{inp['i']}] val={inp['val']!r} ph={inp['ph']!r} "
                f"cls={inp['cls']!r} @({inp['x']},{inp['y']})")

        # 3) 通过坐标定位「活动营销费」input（约 @2869），dump 所在 cell 完整结构
        fee_cell = page.evaluate(
            """() => {
                const roots = [...document.querySelectorAll(
                    '.el-drawer:not([style*="display: none"]), '
                    + '.el-dialog:not([style*="display: none"])')]
                    .filter(r => r.getBoundingClientRect().width > 0);
                const root = roots.find(r => {
                    const s = (r.innerText||'');
                    return s.includes('保存算价');
                }) || roots[0];
                if (!root) return { note: '无抽屉' };
                const out = [];
                [...root.querySelectorAll('input')].forEach((e) => {
                    const r = e.getBoundingClientRect();
                    if (r.width === 0) return;
                    // 活动营销费 input 特征：x 在 2800-2950 区间
                    if (r.x > 2800 && r.x < 2950 && r.y > 500) {
                        const td = e.closest('td');
                        const th = root.querySelectorAll('.vxe-header-column');
                        // 找该列对应的列头文本
                        const rowTd = e.closest('tr');
                        const cellIndex = rowTd ? [...rowTd.children].indexOf(td) : -1;
                        const headerText = (cellIndex >= 0 && th[cellIndex])
                            ? th[cellIndex].innerText.trim() : null;
                        out.push({
                            val: e.value,
                            headerText,
                            cellText: td ? td.innerText : null,
                            cellHtml: td ? td.outerHTML.slice(0, 1200) : null
                        });
                    }
                });
                return out;
            }"""
        )
        log(f"[probe] 活动营销费列结构 ({len(fee_cell)} 处):")
        for r in fee_cell:
            log(f"[probe]   列头: {r['headerText']!r}")
            log(f"[probe]   输入值: {r['val']!r}")
            log(f"[probe]   cell 文本: {r['cellText']!r}")
            log(f"[probe]   cell HTML: {r['cellHtml']}")

        shot = ROOT / "runtime" / "probe_activity_fee.png"
        page.screenshot(path=str(shot), full_page=True)
        log(f"[probe] 截图: {shot}")

        browser.close()


if __name__ == "__main__":
    main()