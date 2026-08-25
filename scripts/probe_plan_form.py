"""全能勘察：dump 加入上架计划 dialog 所有字段 + 平台el-select下拉 + 产品类目面板。全 JS 交互。
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
                        _open_category, SEL_TABLE)


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
        page.evaluate(
            """(args) => {
                const us = args.us, ch = args.ch;
                const tabs = [...document.querySelectorAll('.el-tabs__item, .el-radio-button, span')];
                const findTab = (txt) => tabs.find(e => {
                    const t=(e.innerText||'').trim();
                    return t===txt && e.getBoundingClientRect().width>0;
                });
                const u = findTab(us); if (u) u.click();
                setTimeout(() => { const c = findTab(ch); if (c) c.click(); }, 800);
            }""",
            {"us": pool["region_tab"], "ch": pool["channel"]},
        )
        page.wait_for_timeout(2000)

        for attempt in range(3):
            try:
                _open_category(page, config["category"]["system_path"])
                break
            except RuntimeError as e:
                log(f"[probe] 品类选中失败(第{attempt+1}次): {e}")
                page.keyboard.press("Escape")
                page.wait_for_timeout(1000)
                if attempt == 2:
                    raise
        if pool.get("escape_after_select", True):
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
        safe_click(page, SEL_SEARCH_BTN)
        wait_network_idle_light(page)

        frozen_rows = page.locator(".vxe-table--fixed-left-wrapper .vxe-table--body-wrapper tr")
        cb_td = frozen_rows.first.locator("td.col--checkbox").first
        if cb_td.count():
            cb_td.click(timeout=8000)
            page.wait_for_timeout(400)

        trig = page.locator("button.el-dropdown-selfdefine").first
        if trig.count():
            trig.click(timeout=8000)
            page.wait_for_timeout(800)
        li_pos = page.evaluate(
            """() => {
                const it = [...document.querySelectorAll('.el-dropdown-menu__item')]
                    .find(x => (x.innerText||'').trim() === '直接加入上架计划');
                if (!it) return null;
                const r = it.getBoundingClientRect();
                return {x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2)};
            }"""
        )
        if li_pos:
            page.mouse.click(li_pos["x"], li_pos["y"])

        for _ in range(20):
            page.wait_for_timeout(1000)
            if page.evaluate("""() => [...document.querySelectorAll('.el-dialog')]
                    .some(d => d.offsetParent !== null || d.getBoundingClientRect().width > 100)"""):
                break
        page.wait_for_timeout(2500)
        log("[probe] dialog 就绪")

        # ① dump 所有 label（for + 文本）和关联 form-item 的控件
        all_fields = page.evaluate(
            """() => {
                const dlg = [...document.querySelectorAll('.el-dialog')]
                    .find(d => d.offsetParent !== null || d.getBoundingClientRect().width > 100);
                if (!dlg) return 'NO_DIALOG';
                const res = [];
                dlg.querySelectorAll('.el-form-item').forEach((fi) => {
                    const r = fi.getBoundingClientRect();
                    if (r.width === 0 || r.height === 0) return;
                    const lbl = fi.querySelector('.el-form-item__label, label');
                    const ctrl = fi.querySelector('.el-select, .el-cascader, input, textarea');
                    res.push({
                        label: lbl ? lbl.innerText.trim() : '',
                        for: lbl ? (lbl.getAttribute('for')||'') : '',
                        ctrl: ctrl ? (ctrl.classList ? 
                            (ctrl.classList.contains('el-select') ? 'el-select'
                              : ctrl.classList.contains('el-cascader') ? 'el-cascader'
                              : ctrl.tagName) : ctrl.tagName) : '',
                        ctrlPh: ctrl && ctrl.placeholder ? ctrl.placeholder : '',
                        x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width)
                    });
                });
                return res;
            }"""
        )
        log("[probe] ① 全部字段:")
        for f in (all_fields if isinstance(all_fields, list) else []):
            log(f"[probe]   label={f['label']!r} for={f['for']!r} ctrl={f['ctrl']!r} "
                f"ph={f['ctrlPh']!r} @({f['x']},{f['y']})")

        # ② 点击「平台」el-select（JS），dump 下拉
        page.evaluate(
            """() => {
                const dlg = [...document.querySelectorAll('.el-dialog')]
                    .find(d => d.offsetParent !== null || d.getBoundingClientRect().width > 100);
                const fi = [...dlg.querySelectorAll('.el-form-item')].find(fi2 =>
                    (fi2.querySelector('.el-form-item__label, label')||{}).innerText
                        ? (fi2.querySelector('.el-form-item__label, label').innerText.trim().includes('平台'))
                        : false);
                const sel = fi && fi.querySelector('.el-select');
                if (sel) { const r=sel.getBoundingClientRect(); sel.click();
                    return {x:Math.round(r.x), y:Math.round(r.y)}; }
                return null;
            }"""
        )
        page.wait_for_timeout(2000)
        plat_panel = page.evaluate(
            """() => {
                const panels = [...document.querySelectorAll('.el-select-dropdown')]
                    .filter(s => s.offsetParent !== null);
                if (!panels.length) return 'NO_PANEL';
                return panels.map(s => {
                    const inp = s.querySelector('input');
                    return {hasInput: !!inp, inputPh: inp?inp.placeholder:'',
                            items: [...s.querySelectorAll('.el-select-dropdown__item')].slice(0,8)
                                .map(li => (li.innerText||'').trim())};
                });
            }"""
        )
        log(f"[probe] ② 平台下拉: {plat_panel}")
        page.keyboard.press("Escape")
        page.wait_for_timeout(600)

        # ③ 点击「产品类目」控件（cascader 或 select），dump 面板
        page.evaluate(
            """() => {
                const dlg = [...document.querySelectorAll('.el-dialog')]
                    .find(d => d.offsetParent !== null || d.getBoundingClientRect().width > 100);
                const fi = [...dlg.querySelectorAll('.el-form-item')].find(fi2 => {
                    const l = fi2.querySelector('.el-form-item__label, label');
                    return l && l.innerText.trim().includes('产品类目');
                });
                const c = fi && (fi.querySelector('.el-cascader') || fi.querySelector('.el-select'));
                if (c) { c.click(); return c.className; }
                return null;
            }"""
        )
        page.wait_for_timeout(2000)
        cat_panel = page.evaluate(
            """() => {
                const sels = [...document.querySelectorAll(
                    '.el-cascader__dropdown, .el-cascader-panel, .el-select-dropdown')]
                    .filter(s => s.offsetParent !== null);
                if (!sels.length) return 'NO_PANEL';
                return sels.map(s => {
                    const inp = s.querySelector('input');
                    return {cls: (typeof s.className==='string'?s.className:'').slice(0,30),
                            hasInput: !!inp,
                            items: [...s.querySelectorAll('.el-cascader-node__label, '
                                + '.el-cascader-menu li, .el-select-dropdown__item')].slice(0,15)
                                .map(li => (li.innerText||'').trim())};
                });
            }"""
        )
        log(f"[probe] ③ 产品类目面板: {cat_panel}")
        page.screenshot(path=str(ROOT / "runtime" / "probe_all_fields.png"), full_page=True)

        browser.close()


if __name__ == "__main__":
    main()