"""聚焦诊断（一次性）：打开加入上架计划 dialog，dump 各字段当前值 + 平台下拉结构。
重点：确认平台 el-select 点击后下拉面板是否展开、有哪些选项（含为何 NO_PANEL）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import sync_playwright

from src.config import load_config, log, ROOT
from src.login import _open_context, is_logged_in
from src.dom import wait_network_idle_light, safe_click
from src.phase1 import SEL_SEARCH_BTN, _open_category


def open_dialog(page, config):
    pool = config["product_pool"]
    page.goto(pool["url"], wait_until="domcontentloaded", timeout=60000)
    wait_network_idle_light(page)
    page.evaluate(
        """(args) => {
            const tabs = [...document.querySelectorAll('.el-tabs__item, .el-radio-button, span')];
            const findTab = (txt) => tabs.find(e =>
                (e.innerText||'').trim()===txt && e.getBoundingClientRect().width>0);
            const u = findTab(args.us); if (u) u.click();
            setTimeout(() => { const c = findTab(args.ch); if (c) c.click(); }, 800);
        }""",
        {"us": pool["region_tab"], "ch": pool["channel"]},
    )
    page.wait_for_timeout(2000)
    for a in range(3):
        try:
            _open_category(page, config["category"]["system_path"]); break
        except RuntimeError as e:
            log(f"[diag] 品类失败(第{a+1}次): {e}")
            page.keyboard.press("Escape"); page.wait_for_timeout(1000)
    if pool.get("escape_after_select", True):
        page.keyboard.press("Escape"); page.wait_for_timeout(300)
    safe_click(page, SEL_SEARCH_BTN)
    wait_network_idle_light(page)
    try:
        page.wait_for_selector(".vxe-table--body-wrapper tr", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(1500)
    frozen = page.locator(".vxe-table--fixed-left-wrapper .vxe-table--body-wrapper tr")
    cb = frozen.first.locator("td.col--checkbox").first
    if cb.count():
        cb.click(timeout=8000); page.wait_for_timeout(300)
    trig = page.locator("button.el-dropdown-selfdefine").first
    if trig.count():
        trig.click(timeout=8000); page.wait_for_timeout(800)
    li = page.evaluate(
        """() => {
            const it=[...document.querySelectorAll('.el-dropdown-menu__item')]
                .find(x=>(x.innerText||'').trim()==='直接加入上架计划');
            if(!it) return null;
            const r=it.getBoundingClientRect();
            return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)};
        }"""
    )
    if li:
        page.mouse.click(li["x"], li["y"])
    for _ in range(15):
        page.wait_for_timeout(1000)
        if page.evaluate(
            """() => [...document.querySelectorAll('.el-dialog')]
                .some(d => d.offsetParent !== null || d.getBoundingClientRect().width > 100)"""
        ):
            return True
    return False


def main():
    config = load_config()
    with sync_playwright() as p:
        browser, context = _open_context(p, config, headless=config["app"]["headless"],
                                         storage=ROOT / config["app"]["storage_state"])
        page = context.new_page()
        if not is_logged_in(page):
            log("[diag] ✗ 未登录"); browser.close(); sys.exit(1)
        if not open_dialog(page, config):
            log("[diag] ✗ dialog 未弹出"); browser.close(); sys.exit(1)
        page.wait_for_timeout(2000)
        log("[diag] dialog 已打开")

        # dump 各字段当前值 + 控件类型
        dump = page.evaluate(
            """() => {
                const dlg=[...document.querySelectorAll('.el-dialog')]
                    .find(d=>d.offsetParent!==null||d.getBoundingClientRect().width>100);
                if(!dlg) return 'NO_DIALOG';
                const out=[];
                dlg.querySelectorAll('.el-form-item').forEach(fi=>{
                    const r=fi.getBoundingClientRect();
                    if(r.width===0||r.height===0) return;
                    const l=fi.querySelector('.el-form-item__label,label');
                    const ctrl=fi.querySelector('.el-select,.el-cascader,input');
                    let kind=null;
                    if(ctrl) kind=ctrl.classList.contains('el-cascader')?'cascader'
                        :ctrl.classList.contains('el-select')?'select'
                        :ctrl.tagName.toLowerCase()==='input'?'input':ctrl.tagName;
                    let selVal='';
                    if(ctrl&&ctrl.classList.contains('el-select')){
                        const wrap=ctrl.querySelector('.el-select__selected-item,.el-select__selected-value,.el-select__placeholder');
                        selVal=wrap?(wrap.innerText||'').trim():'';
                        if(!selVal){const inp=ctrl.querySelector('input');selVal=inp?inp.value:'';}
                    }
                    let inpVal='';
                    if(kind==='input'){inpVal=ctrl&&ctrl.value?ctrl.value:'';}
                    out.push({label:l?JSON.stringify(l.innerText||''):'NO_LABEL',
                              for:l?(l.getAttribute('for')||''):'',kind,selVal,inpVal});
                });
                return out;
            }"""
        )
        log("[diag] 表单字段:")
        for f in (dump if isinstance(dump, list) else []):
            log(f"[diag]   {f['label']} for={f['for']} {f['kind']} sel={f['selVal']!r} inp={f['inpVal']!r}")

        # mouse 点击平台 el-select，dump 下拉是否展开 + 选项
        plat = page.evaluate(
            """() => {
                const dlg=[...document.querySelectorAll('.el-dialog')]
                    .find(d=>d.offsetParent!==null||d.getBoundingClientRect().width>100);
                const fi=[...dlg.querySelectorAll('.el-form-item')].find(f=>{
                    const l=f.querySelector('.el-form-item__label,label');
                    return l&&(l.innerText||'').trim()==='平台';
                });
                const sel=fi&&fi.querySelector('.el-select');
                if(!sel) return null;
                const r=sel.getBoundingClientRect();
                return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2),
                        w:Math.round(r.width),h:Math.round(r.height)};
            }"""
        )
        if plat:
            page.mouse.click(plat["x"], plat["y"])
            page.wait_for_timeout(1500)
        st = page.evaluate(
            """() => {
                const dlg=[...document.querySelectorAll('.el-dialog')]
                    .find(d=>d.offsetParent!==null||d.getBoundingClientRect().width>100);
                const loading=dlg&&dlg.querySelector('.el-loading-mask,.vxe-loading');
                const dd=[...document.querySelectorAll('.el-select-dropdown')];
                return {
                    dialog:!!dlg,
                    loading: loading ? (loading.offsetParent!==null
                        || loading.getBoundingClientRect().width>10) : false,
                    dropdowns: dd.map(d=>({
                        visible:d.offsetParent!==null,
                        items:[...d.querySelectorAll('.el-select-dropdown__item')]
                            .map(li=>(li.innerText||'').trim()).slice(0,15),
                    })),
                };
            }"""
        )
        log(f"[diag] 点击平台后: {st}")
        page.screenshot(path=str(ROOT / "runtime" / "diag_plat_dropdown.png"), full_page=True)
        browser.close()


if __name__ == "__main__":
    main()