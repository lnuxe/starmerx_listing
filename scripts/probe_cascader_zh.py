"""勘察：语言选「中文」后，产品类目 cascader 的中文 4 级路径文本。

目的：拿到平台类目在中文语言下的逐级中文文本，用于配置 `platform_path_zh`。
不提交任何数据（不点「确定加入」）。

流程：打开产品池 → 切美区/多渠道 → 选品类 → 搜索 → 勾选首行 → 打开
「直接加入上架计划」dialog → 选品牌(解锁) → 选语言「中文」→ 展开产品类目
cascader → 逐级点击 dump 每级文本直到叶子。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import sync_playwright

from src.config import load_config, log, ROOT
from src.login import _open_context, is_logged_in
from src.dom import wait_network_idle_light, safe_click
from src.phase1 import (SEL_TAB_US_POOL, SEL_TAB_CHANNEL, SEL_SEARCH_BTN,
                        SEL_TABLE, _open_category, _open_plan_dialog_via_row)


def _pick_form_select(page, label: str, value: str) -> None:
    """展开 label 对应的 el-select 并点选 value（element click）。"""
    for _ in range(15):
        ok = page.evaluate(
            """(label) => {
                const dlg = [...document.querySelectorAll('.el-dialog')]
                    .find(d => d.offsetParent !== null || d.getBoundingClientRect().width > 100);
                if (!dlg) return false;
                const f = [...dlg.querySelectorAll('.el-form-item')].find(fi => {
                    const l = fi.querySelector('.el-form-item__label, label');
                    return l && (l.innerText || '').trim() === label;
                });
                const sel = f && f.querySelector('.el-select');
                if (!sel) return false;
                const r = sel.getBoundingClientRect();
                if (r.width <= 0 || r.height <= 0) return false;
                (sel.querySelector('.el-select__wrapper, .el-input__wrapper, input') || sel).click();
                return true;
            }""",
            label,
        )
        if ok:
            break
        page.wait_for_timeout(400)
    page.wait_for_timeout(800)
    for _ in range(10):
        hit = page.evaluate(
            """(value) => {
                const panels = [...document.querySelectorAll('.el-select-dropdown')]
                    .filter(s => { const r = s.getBoundingClientRect();
                                   return r.width > 0 && r.height > 0; });
                for (const p of panels) {
                    for (const li of p.querySelectorAll('.el-select-dropdown__item')) {
                        const t = (li.innerText || '').trim().replace(/\\s+/g, ' ');
                        if (t === value) { li.click(); return t; }
                    }
                }
                return null;
            }""",
            value,
        )
        if hit:
            page.wait_for_timeout(500)
            log(f"[probe] ✓ {label} → {hit}")
            return
        page.wait_for_timeout(400)


def _pick_source_lang_zh(page) -> None:
    """产品类目行内嵌「语言」下拉：定位并点击展开，选「中文」。"""
    for _ in range(30):
        r = page.evaluate(
            """() => {
                const dlg = [...document.querySelectorAll('.el-dialog')]
                    .find(d => d.offsetParent !== null || d.getBoundingClientRect().width > 100);
                if (!dlg) return false;
                const f = [...dlg.querySelectorAll('.el-form-item')].find(fi => {
                    const l = fi.querySelector('.el-form-item__label, label');
                    return l && (l.innerText || '').trim() === '产品类目';
                });
                const sel = f && f.querySelector('.category-options .el-select');
                if (!sel) return false;
                const r = sel.getBoundingClientRect();
                if (r.width <= 0 || r.height <= 0) return false;
                (sel.querySelector('.el-select__wrapper, .el-input__wrapper, input') || sel).click();
                return true;
            }"""
        )
        if r:
            break
        page.wait_for_timeout(500)
    page.wait_for_timeout(1200)
    for _ in range(10):
        hit = page.evaluate(
            """() => {
                const panels = [...document.querySelectorAll('.el-select-dropdown')]
                    .filter(s => { const r = s.getBoundingClientRect();
                                   return r.width > 0 && r.height > 0; });
                for (const p of panels) {
                    for (const li of p.querySelectorAll('.el-select-dropdown__item')) {
                        const t = (li.innerText || '').trim().replace(/\\s+/g, ' ');
                        if (t === 'Chinese' || t === '中文') { li.click(); return t; }
                    }
                }
                return null;
            }"""
        )
        if hit:
            page.wait_for_timeout(800)
            log(f"[probe] ✓ 语言 → {hit}")
            # 收起残留的语言下拉面板（点 dialog 标题），避免遮挡 cascader
            page.evaluate(
                """() => {
                    const dlg = [...document.querySelectorAll('.el-dialog')]
                        .find(d => d.offsetParent !== null || d.getBoundingClientRect().width > 100);
                    const hd = dlg && (dlg.querySelector('.el-dialog__header')
                        || dlg.querySelector('.el-dialog__title'));
                    if (hd) { const r = hd.getBoundingClientRect();
                              window.__px = r.x + Math.min(r.width / 2, 120);
                              window.__py = r.y + r.height / 2; }
                }"""
            )
            try:
                page.mouse.click(page.evaluate("window.__px"),
                                 page.evaluate("window.__py"))
            except Exception:
                pass
            page.wait_for_timeout(400)
            return
        page.wait_for_timeout(400)


def _walk_cascader(page) -> None:
    """逐级点击产品类目 cascader，dump 每级文本，直到叶子。"""
    path = []
    for depth in range(1, 8):
        labels = page.evaluate(
            """() => {
                const menus = [...document.querySelectorAll('.el-cascader-menu')]
                    .filter(m => { const r = m.getBoundingClientRect();
                                   return r.width > 0 && r.height > 0; });
                for (const m of menus) {
                    const nodes = [...m.querySelectorAll('.el-cascader-node')].map(x => {
                        const t = (x.querySelector('.el-cascader-node__label') || x)
                            .innerText.replace(/\\s+/g, ' ').trim();
                        const r = x.getBoundingClientRect();
                        const isLeaf = x.classList.contains('is-leaf')
                            || !!x.querySelector('.el-cascader-node__postfix');
                        return {t, x: Math.round(r.x + r.width / 2),
                                y: Math.round(r.y + r.height / 2), isLeaf};
                    }).filter(n => n.t && n.t !== '请选择');
                    if (nodes.length) return nodes;
                }
                return [];
            }"""
        )
        if not labels:
            log(f"[probe] 第{depth}级：无可见菜单，结束")
            break
        log(f"[probe] 第{depth}级可见: {[n['t'] for n in labels[:12]]}")
        first = labels[0]
        path.append(first["t"])
        if first["isLeaf"]:
            log(f"[probe] 到叶子。中文路径: {path}")
            break
        page.mouse.click(first["x"], first["y"])
        page.wait_for_timeout(700)


def main() -> None:
    config = load_config()
    pool = config["product_pool"]

    with sync_playwright() as p:
        browser, context = _open_context(p, config, headless=config["app"]["headless"],
                                         storage=ROOT / config["app"]["storage_state"])
        page = context.new_page()
        if not is_logged_in(page):
            log("[probe] ✗ 未登录")
            browser.close()
            sys.exit(1)

        page.goto(pool["url"], wait_until="domcontentloaded", timeout=60000)
        wait_network_idle_light(page)
        safe_click(page, SEL_TAB_US_POOL)
        page.wait_for_timeout(800)
        safe_click(page, SEL_TAB_CHANNEL)
        page.wait_for_timeout(800)

        _open_category(page, config["category"]["system_path"])
        if pool.get("escape_after_select", True):
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
        safe_click(page, SEL_SEARCH_BTN)
        wait_network_idle_light(page)

        # 等待表格行加载（避免 vxe-loading 遮罩拦截点击）
        try:
            page.wait_for_selector(".vxe-table--body-wrapper tr", timeout=15000)
        except Exception:
            pass
        for _ in range(20):
            page.wait_for_timeout(500)
            if page.locator(SEL_TABLE).first.locator("tr").count() > 0:
                break

        # 勾选首行
        frozen = page.locator(".vxe-table--fixed-left-wrapper .vxe-table--body-wrapper tr")
        cb_td = frozen.first.locator("td.col--checkbox").first
        if not cb_td.count():
            cb_td = page.locator(SEL_TABLE).first.locator("tr").first \
                .locator("td.col--checkbox").first
        cb_td.click(timeout=8000)
        page.wait_for_timeout(500)

        # 打开「直接加入上架计划」dialog
        if not _open_plan_dialog_via_row(page, row_index=0):
            log("[probe] ✗ dialog 未弹出")
            browser.close()
            sys.exit(1)
        page.wait_for_timeout(2000)
        log("[probe] ✓ dialog 已弹出")

        # 解锁顺序：品牌(select) → 语言(中文) → 类目
        _pick_form_select(page, "品牌", config["plan"]["brand"])
        _pick_source_lang_zh(page)

        # 展开产品类目 cascader 并逐级 dump（点击 → 校验面板展开，轮询等待加载完成）
        opened = False
        for _ in range(30):
            cas_rect = page.evaluate(
                """() => {
                    const dlg = [...document.querySelectorAll('.el-dialog')]
                        .find(d => d.offsetParent !== null || d.getBoundingClientRect().width > 100);
                    if (!dlg) return null;
                    const f = [...dlg.querySelectorAll('.el-form-item')].find(fi => {
                        const l = fi.querySelector('.el-form-item__label, label');
                        return l && (l.innerText || '').trim() === '产品类目';
                    });
                    const cas = f && f.querySelector('.el-cascader');
                    if (!cas) return null;
                    const r = cas.getBoundingClientRect();
                    if (r.width <= 0 || r.height <= 0) return null;
                    return {x: Math.round(r.x + r.width / 2),
                            y: Math.round(r.y + r.height / 2)};
                }"""
            )
            if cas_rect:
                page.mouse.click(cas_rect["x"], cas_rect["y"])
                page.wait_for_timeout(1500)   # 单次点击后给足动画+加载时间
                opened = page.evaluate(
                    """() => [...document.querySelectorAll('.el-cascader-menu')]
                        .some(m => { const r = m.getBoundingClientRect();
                                     return r.width > 0 && r.height > 0; })"""
                )
                if opened:
                    break
                # 未展开：点 dialog 标题安全收起后再重试，避免 toggle 抖动
                page.evaluate(
                    """() => {
                        const dlg = [...document.querySelectorAll('.el-dialog')]
                            .find(d => d.offsetParent !== null
                                || d.getBoundingClientRect().width > 100);
                        const hd = dlg && (dlg.querySelector('.el-dialog__header')
                            || dlg.querySelector('.el-dialog__title'));
                        if (hd) { const r = hd.getBoundingClientRect();
                                  window.__px = r.x + Math.min(r.width / 2, 120);
                                  window.__py = r.y + r.height / 2; }
                    }"""
                )
                try:
                    page.mouse.click(page.evaluate("window.__px"),
                                     page.evaluate("window.__py"))
                except Exception:
                    pass
                page.wait_for_timeout(300)
            page.wait_for_timeout(500)
        if not opened:
            log("[probe] ✗ 产品类目 cascader 面板未能展开")
            # 诊断：dump cascader 元素状态 + 遮罩 + 语言值 + 截图，定位阻塞点
            try:
                diag = page.evaluate(
                    """() => {
                        const dlg = [...document.querySelectorAll('.el-dialog')]
                            .find(d => d.offsetParent !== null || d.getBoundingClientRect().width > 100);
                        const f = dlg && [...dlg.querySelectorAll('.el-form-item')].find(fi => {
                            const l = fi.querySelector('.el-form-item__label, label');
                            return l && (l.innerText || '').trim() === '产品类目';
                        });
                        const cas = f && f.querySelector('.el-cascader');
                        const casInput = cas && cas.querySelector('input');
                        const r = cas ? cas.getBoundingClientRect() : null;
                        const langSel = f && f.querySelector('.category-options .el-select');
                        const langTxt = langSel && ((
                            langSel.querySelector('.el-select__selected-item,.el-select__selected-value,'
                                + '.el-select__placeholder,.el-select__tags-text') || {}).innerText || '').trim();
                        const masks = [...document.querySelectorAll('.el-loading-mask, .el-overlay.is-mask, '
                            + '.vxe-loading.is--visible, .el-message-box, .el-popup-parent--hidden')]
                            .filter(e => { const rr = e.getBoundingClientRect();
                                           return rr.width > 0 && rr.height > 0; });
                        const casPoint = r && r.width > 0 ? {
                            x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2)} : null;
                        return {
                            casExists: !!cas,
                            casRect: r ? [Math.round(r.x), Math.round(r.y),
                                          Math.round(r.width), Math.round(r.height)] : null,
                            casDisabled: cas ? (cas.classList.contains('is-disabled')
                                || (casInput && casInput.disabled)) : null,
                            casReadonly: casInput ? casInput.readOnly : null,
                            langTxt,
                            langVal: langSel ? (langSel.__vue__ ? (langSel.__vue__.value
                                || langSel.__vue__.$children?.[0]?.value || null) : null) : null,
                            visibleMasks: masks.map(m => (m.className || m.tagName)
                                .toString().slice(0, 50)),
                            casPoint,
                        };
                    }"""
                )
                log(f"[probe]   cascader 诊断: {diag}")
                page.screenshot(path=str(ROOT / "runtime" / "probe_cascader_diag.png"))
            except Exception as e:
                log(f"[probe]   诊断失败: {e}")
            browser.close()
            sys.exit(1)
        page.wait_for_timeout(600)
        _walk_cascader(page)

        browser.close()


if __name__ == "__main__":
    main()