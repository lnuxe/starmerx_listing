"""勘察：选完平台/站点/店铺/品牌后，产品类目行「语言」下拉是否解锁及选项文本。

流程：打开 dialog → 依次选平台/站点/店铺/品牌 → dump 语言下拉状态与选项。
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


def _lang_state(page) -> str:
    """读产品类目行语言下拉当前值（选中文本 / placeholder）。"""
    return page.evaluate(
        """() => {
            const dlg=[...document.querySelectorAll('.el-dialog')]
                .find(d=>d.offsetParent!==null||d.getBoundingClientRect().width>100);
            const f=[...dlg.querySelectorAll('.el-form-item')].find(fi=>{
                const l=fi.querySelector('.el-form-item__label,label');
                return l&&(l.innerText||'').trim()==='产品类目';});
            const sel=f&&f.querySelector('.category-options .el-select');
            if(!sel) return 'NO_SEL';
            const w=sel.querySelector('.el-select__selected-item,'
                +'.el-select__selected-value,.el-select__placeholder,.el-select__tags-text');
            const inp=sel.querySelector('input');
            const dis=sel.classList.contains('is-disabled')
                || !!sel.querySelector('input.is-disabled');
            return JSON.stringify({val:w?(w.innerText||'').trim():inp?inp.value:'', disabled:dis});
        }"""
    )


def _lang_select_point(page):
    """返回产品类目行语言下拉的中心坐标或 None。"""
    return page.evaluate(
        """() => {
            const dlg=[...document.querySelectorAll('.el-dialog')]
                .find(d=>d.offsetParent!==null||d.getBoundingClientRect().width>100);
            const f=[...dlg.querySelectorAll('.el-form-item')].find(fi=>{
                const l=fi.querySelector('.el-form-item__label,label');
                return l&&(l.innerText||'').trim()==='产品类目';});
            const sel=f&&f.querySelector('.category-options .el-select');
            if(!sel) return null;
            const r=sel.getBoundingClientRect();
            return {x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2)};
        }"""
    )


def _click_form_select(page, label_text: str, value: str) -> str:
    """点击 dialog 内 label 对应的 el-select，选 value，返回实际选中文本。"""
    pt = page.evaluate(
        """(labelText) => {
            const dlg=[...document.querySelectorAll('.el-dialog')]
                .find(d=>d.offsetParent!==null||d.getBoundingClientRect().width>100);
            const f=[...dlg.querySelectorAll('.el-form-item')].find(fi=>{
                const l=fi.querySelector('.el-form-item__label,label');
                return l&&(l.innerText||'').trim()===labelText;});
            const sel=f&&f.querySelector('.el-select');
            if(!sel) return null;
            const r=sel.getBoundingClientRect();
            return {x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2)};
        }""",
        label_text,
    )
    if not pt:
        return f'NO_FIELD({label_text})'
    page.mouse.click(pt["x"], pt["y"])
    page.wait_for_timeout(800)
    for _ in range(8):
        hit = page.evaluate(
            """(value) => {
                const panels=[...document.querySelectorAll('.el-select-dropdown')]
                    .filter(s=>{const r=s.getBoundingClientRect();
                                return r.width>0&&r.height>0;});
                const hits=[];
                for(const p of panels)
                    for(const li of p.querySelectorAll('.el-select-dropdown__item')){
                        const t=(li.innerText||'').trim().replace(/\\s+/g,' ');
                        if(t.includes(value)&&t.length<=40) hits.push(li);}
                if(!hits.length) return null;
                hits.sort((a,b)=>{
                    const ta=(a.innerText||'').trim().replace(/\\s+/g,' ');
                    const tb=(b.innerText||'').trim().replace(/\\s+/g,' ');
                    return ta.length-tb.length;});
                const r=hits[0].getBoundingClientRect();
                return {x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2),
                        txt:(hits[0].innerText||'').trim().replace(/\\s+/g,' ')};
            }""",
            value,
        )
        if hit:
            page.mouse.click(hit["x"], hit["y"])
            page.wait_for_timeout(500)
            return hit["txt"]
        page.wait_for_timeout(500)
    return f'NO_OPT({value})'


def main() -> None:
    config = load_config()
    pool = config["product_pool"]
    plan = config["plan"]

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
        for _ in range(3):
            try:
                _open_category(page, config["category"]["system_path"])
                break
            except RuntimeError:
                page.keyboard.press("Escape")
                page.wait_for_timeout(1000)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        safe_click(page, SEL_SEARCH_BTN)
        wait_network_idle_light(page)
        try:
            page.wait_for_selector(".vxe-table--body-wrapper tr", timeout=15000)
        except Exception:
            pass
        for _ in range(20):
            page.wait_for_timeout(500)
            if page.locator(SEL_TABLE).first.locator("tr").count() > 0:
                break
        frozen = page.locator(".vxe-table--fixed-left-wrapper .vxe-table--body-wrapper tr")
        cb_td = frozen.first.locator("td.col--checkbox").first
        if not cb_td.count():
            cb_td = page.locator(SEL_TABLE).first.locator("tr").first \
                .locator("td.col--checkbox").first
        for _ in range(3):
            cb_td.click(timeout=8000)
            page.wait_for_timeout(400)
            if cb_td.evaluate(
                """(td) => td.classList.contains('is--checked')
                    || !!td.querySelector('.is--checked, [aria-checked=true]')"""
            ):
                break
            page.wait_for_timeout(600)
        if not _open_plan_dialog_via_row(page, row_index=0):
            log("[probe] ✗ dialog 未弹出")
            browser.close()
            sys.exit(1)
        page.wait_for_timeout(2000)

        log(f"[probe] 语言下拉(初始): {_lang_state(page)}")

        for lbl, val in [("平台", plan["platform"]), ("站点", plan["site"]),
                         ("店铺", plan["store"]), ("品牌", plan["brand"])]:
            got = _click_form_select(page, lbl, val)
            log(f"[probe] 选 {lbl} → {got!r}")
        page.wait_for_timeout(800)
        log(f"[probe] 语言下拉(选完品牌后): {_lang_state(page)}")

        # 尝试展开语言下拉并 dump 选项
        pt = _lang_select_point(page)
        if pt:
            page.mouse.click(pt["x"], pt["y"])
        page.wait_for_timeout(1500)
        opts = page.evaluate(
            """() => {
                const panels=[...document.querySelectorAll('.el-select-dropdown')]
                    .filter(s=>{const r=s.getBoundingClientRect();
                                return r.width>0&&r.height>0;});
                if(!panels.length) return 'NO_VISIBLE_PANEL';
                return panels.map(p=>[...p.querySelectorAll('.el-select-dropdown__item')]
                    .map(li=>(li.innerText||'').trim().replace(/\\s+/g,' ')));
            }"""
        )
        log(f"[probe] 语言下拉选项: {opts!r}")

        page.keyboard.press("Escape")
        page.wait_for_timeout(1500)
        browser.close()


if __name__ == "__main__":
    main()