"""勘察 Phase2 主表格「图片/自动生成图文状态/文案/操作」列内容，定位图片编辑入口。

已知：col10/11=申请实例、col12=利润测算、col13=编辑属性。
待查：图片编辑（8张图/白底主图/SKU颜色标签）入口——可能在「图片」列缩略图或「自动生成图文状态」列。
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
        log(f"[probe] 已进入上架计划页: {page.url}")

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

        # dump 首行每个单元格的文本 + 是否含 img / button / input
        cells = page.evaluate(
            """() => {
                const t = document.querySelector('.vxe-table');
                const row = t.querySelector('.vxe-body--row, .vxe-row');
                if (!row) return [];
                const out = [];
                row.querySelectorAll('td, .vxe-body--column').forEach((c, ci) => {
                    const r = c.getBoundingClientRect();
                    const imgs = c.querySelectorAll('img').length;
                    const btns = [...c.querySelectorAll('button')].map(b =>
                        (b.innerText||'').trim()).filter(Boolean);
                    const inputs = c.querySelectorAll('input').length;
                    const txt = (c.innerText||'').trim().replace(/\\s+/g,' ').slice(0,50);
                    out.push({ col: ci, x: Math.round(r.x),
                               imgs, inputs, btns, txt });
                });
                return out;
            }"""
        )
        log(f"[probe] 首行各列详情:")
        for c in cells:
            log(f"[probe]   col{c['col']} x={c['x']} img={c['imgs']} input={c['inputs']} "
                f"btn={c['btns']} text={c['txt']}")

        # dump 自动生成图文状态列的样式（是否有状态标签）
        state_el = page.evaluate(
            """() => {
                const t = document.querySelector('.vxe-table');
                const row = t.querySelector('.vxe-body--row, .vxe-row');
                if (!row) return null;
                const heads = [...t.querySelectorAll('.vxe-header-column, th')]
                    .map(h => (h.innerText||'').trim());
                const idx = heads.indexOf('自动生成图文状态');
                if (idx < 0) return { heads };
                const cell = row.querySelectorAll('td, .vxe-body--column')[idx];
                return { heads, cell_html: cell.innerHTML.slice(0, 500) };
            }"""
        )
        log(f"[probe] 自动生成图文状态列: {state_el}")

        # 尝试点击首行「图片」列缩略图，看是否打开图片编辑
        img_col = page.evaluate(
            """() => {
                const t = document.querySelector('.vxe-table');
                const row = t.querySelector('.vxe-body--row, .vxe-row');
                if (!row) return -1;
                const heads = [...t.querySelectorAll('.vxe-header-column, th')]
                    .map(h => (h.innerText||'').trim());
                return heads.indexOf('图片');
            }"""
        )
        log(f"[probe] 图片列 index: {img_col}")
        if img_col >= 0:
            try:
                img_thumb = page.locator(
                    f".vxe-body--row .vxe-body--column:nth-child({img_col+1}) img"
                ).first
                if img_thumb.count():
                    img_thumb.click(timeout=8000)
                    page.wait_for_timeout(3000)
                    log(f"[probe] 已点击图片缩略图，URL: {page.url}")
                    # dump 弹窗
                    dlg = page.evaluate(
                        """() => {
                            const roots = [...document.querySelectorAll(
                                '.el-drawer:not([style*="display: none"]), '
                                + '.el-dialog:not([style*="display: none"])')];
                            if (!roots.length) return '（无弹窗）';
                            return roots.map((root, i) => {
                                const title = (root.querySelector(
                                    '.el-drawer__title, .el-dialog__title')||{})
                                    .innerText||'';
                                const labels = [...root.querySelectorAll(
                                    'label, .el-form-item__label, button')]
                                    .filter(e => e.offsetParent !== null)
                                    .map(e => (e.innerText||'').trim())
                                    .filter(Boolean).slice(0, 60);
                                return `弹窗${i}[${title}]: ${labels.join(' | ')}`;
                            }).join('\\n');
                        }"""
                    )
                    log(f"[probe] 图片弹窗: {dlg}")
                    shot = ROOT / "runtime" / "image_col_click.png"
                    page.screenshot(path=str(shot), full_page=True)
                    log(f"[probe] 截图: {shot}")
            except Exception as e:
                log(f"[probe] 点击图片列失败: {e}")

        browser.close()


if __name__ == "__main__":
    main()