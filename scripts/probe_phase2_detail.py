"""勘察 Phase2 详情页（headful）——逐个点击表格行内 4 个「编辑」按钮，确认各自的编辑功能。

复用 probe_phase2.py 已验证的导航（.sidebar-container + text=上架计划）。
目标：确认 4 个「编辑」按钮分别对应图片编辑 / 价格测算 / 实例管理 等功能。
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


def _goto_plan(page, config: dict) -> None:
    page.goto(config["app"]["base_url"], wait_until="domcontentloaded", timeout=60000)
    wait_network_idle_light(page)
    page.wait_for_timeout(2500)
    if not is_logged_in(page):
        raise RuntimeError("未登录")
    sidebar = page.locator(".sidebar-container")
    sm = sidebar.locator(SEL_MENU_SALES).first
    if sm.count():
        sm.click(timeout=8000)
        page.wait_for_timeout(1500)
    sub = sidebar.locator(SEL_SUB_LISTING_PLAN).first
    if sub.count():
        sub.click(timeout=8000)
        page.wait_for_timeout(2500)
        log(f"[probe] 已进入上架计划页: {page.url}")
    else:
        raise RuntimeError("未找到上架计划子菜单")


def _dump_landing(page, label: str, max_el: int = 150) -> None:
    """dump 当前可见弹窗/抽屉内容。"""
    log(f"===== {label} 结构勘察 =====")
    body = page.evaluate(
        """(maxEl) => {
            const roots = [...document.querySelectorAll(
                '.el-dialog:not([style*="display: none"]), '
                + '.el-drawer:not([style*="display: none"]), '
                + '.el-message-box')];
            if (!roots.length) return '（无可见弹窗）';
            return roots.map((root, ri) => {
                const title = (root.querySelector('.el-dialog__title, .el-drawer__title')
                    || {}).innerText || '';
                const els = [...root.querySelectorAll('button, input, select, textarea, '
                    + '.el-tabs__item, label, .el-form-item__label, .el-input__inner, '
                    + '.el-drawer__header, .el-drawer__title, th, .vxe-cell')]
                    .filter(e => e.offsetParent !== null).slice(0, maxEl)
                    .map((e, i) => {
                        const r = e.getBoundingClientRect();
                        const txt = (e.innerText || e.value || e.placeholder || '')
                            .trim().replace(/\\s+/g, ' ').slice(0, 40);
                        return `${i}:<${e.tagName.toLowerCase()}> ${txt} @(${Math.round(r.x)},${Math.round(r.y)})`;
                    }).join('\\n');
                return `--- 弹窗${ri}[标题:${title}] ---\\n${els}`;
            }).join('\\n');
        }""",
        max_el,
    )
    log(f"[probe] 弹窗内元素:\\n{body}")

    shot = ROOT / "runtime" / f"detail_{label}.png"
    shot.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(shot), full_page=True)
    log(f"[probe] 截图: {shot}")


def _close_drawer(page) -> None:
    """关闭当前打开的抽屉：先点关闭按钮，再 ESC，循环直到抽屉消失。"""
    for _ in range(5):
        vis = page.evaluate(
            """() => {
                const w = document.querySelector(
                    '.el-drawer__wrapper:not([style*="display: none"]), '
                    + '.el-dialog__wrapper:not([style*="display: none"])');
                return !!w;
            }"""
        )
        if not vis:
            log("[probe] 抽屉已关闭")
            return
        # 尝试点关闭按钮
        try:
            close = page.locator(
                ".el-drawer__close-btn, .el-dialog__headerbtn, "
                + ".el-drawer__header button, .el-dialog__header button"
            ).first
            if close.count() and close.is_visible():
                close.click(timeout=2000)
                page.wait_for_timeout(800)
                continue
        except Exception:
            pass
        # 尝试 ESC
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(800)
        except Exception:
            pass
    log("[probe] ⚠ 抽屉可能未完全关闭")

def main() -> None:
    config = load_config()
    # 要勘察的编辑按钮列索引：默认全部，可用 argv 指定单个（0..3）
    target = None
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        target = int(sys.argv[1])

    col_names = {0: "col10", 1: "col11", 2: "col12", 3: "col13"}
    cols = [target] if target is not None else [0, 1, 2, 3]

    with sync_playwright() as p:
        browser, context = _open_context(p, config, headless=False,
                                         storage=ROOT / config["app"]["storage_state"])
        page = context.new_page()
        _goto_plan(page, config)

        # 等待表格出现数据行（异步加载，最长 20s）
        log("[probe] 等待表格数据加载...")
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

        # 逐列勘察（每列一个独立会话最可靠）
        for i in cols:
            edit_btns = page.locator(".vxe-table button:has-text('编辑')")
            total = edit_btns.count()
            log(f"[probe] 表格内「编辑」按钮总数: {total}")
            if total <= i:
                log(f"[probe] 无第{i}个编辑按钮，跳过")
                continue
            try:
                edit_btns.nth(i).click(timeout=8000)
                page.wait_for_timeout(3000)
                log(f"[probe] === 点击第{i}个编辑按钮（{col_names[i]}）===")
                _dump_landing(page, f"edit_col{i}")
            except Exception as e:
                log(f"[probe] 第{i}个编辑按钮勘察失败: {e}")
            if target is None:
                # 多列模式：尝试关闭抽屉
                _close_drawer(page)

        browser.close()


if __name__ == "__main__":
    main()