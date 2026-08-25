"""一次性聚焦诊断：验证「直接加入上架计划」菜单项点击 → dialog 弹出的稳定性。
多次重试，dump 每次点击后的 dialog 状态、下拉菜单状态、触发请求。
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


def main():
    config = load_config()
    pool = config["product_pool"]
    with sync_playwright() as p:
        browser, context = _open_context(p, config, headless=config["app"]["headless"],
                                         storage=ROOT / config["app"]["storage_state"])
        page = context.new_page()
        if not is_logged_in(page):
            log("[diag] ✗ 未登录"); browser.close(); sys.exit(1)

        page.goto(pool["url"], wait_until="domcontentloaded", timeout=60000)
        wait_network_idle_light(page)
        page.evaluate(
            """(args) => {
                const tabs=[...document.querySelectorAll('.el-tabs__item,.el-radio-button,span')];
                const find=(t)=>tabs.find(e=>(e.innerText||'').trim()===t
                    &&e.getBoundingClientRect().width>0);
                const u=find(args.us); if(u) u.click();
                setTimeout(()=>{const c=find(args.ch); if(c) c.click();},800);
            }""",
            {"us": pool["region_tab"], "ch": pool["channel"]},
        )
        page.wait_for_timeout(2000)
        for a in range(3):
            try:
                _open_category(page, config["category"]["system_path"]); break
            except RuntimeError as e:
                log(f"[diag] 品类失败({a+1}): {e}")
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

        # 监听网络请求（记录「加入上架计划」相关请求）
        reqs = []
        def on_req(req):
            if any(k in req.url for k in ["amazon_europe_stores", "template", "store_and_brand",
                                            "product_pool_view", "product_identifier"]):
                reqs.append(f"{req.method} {req.url.split('/')[-1]}")
        page.on("request", on_req)

        # 勾选第一行
        frozen = page.locator(".vxe-table--fixed-left-wrapper .vxe-table--body-wrapper tr")
        cb = frozen.first.locator("td.col--checkbox").first
        if cb.count():
            cb.click(timeout=8000); page.wait_for_timeout(300)
        # 验证勾选态
        chk = cb.evaluate(
            """(td) => td.classList.contains('is--checked')
                || !!td.querySelector('.is--checked,[aria-checked=true]')"""
        )
        log(f"[diag] 勾选态: {chk}")

        trig = page.locator("button.el-dropdown-selfdefine").first
        if not trig.count():
            log("[diag] ✗ 无 trigger"); browser.close(); sys.exit(1)

        # 多次点击测试
        for attempt in range(3):
            reqs.clear()
            trig.click(timeout=8000)
            page.wait_for_timeout(900)
            # 下拉菜单是否展开
            menu_visible = page.evaluate(
                """() => {
                    const m=[...document.querySelectorAll('.el-dropdown-menu, .el-popper')]
                        .filter(e=>{const r=e.getBoundingClientRect();
                            return r.width>0&&r.height>0
                                && (e.innerText||'').includes('直接加入上架计划');});
                    return m.length>0;
                }"""
            )
            log(f"[diag] 第{attempt+1}次点击 trigger → 菜单可见: {menu_visible}")
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
            # 轮询 dialog 20s
            dlg=False
            for _ in range(20):
                page.wait_for_timeout(1000)
                dlg=page.evaluate(
                    """()=>[...document.querySelectorAll('.el-dialog')]
                        .some(d=>d.offsetParent!==null||d.getBoundingClientRect().width>100)"""
                )
                if dlg: break
            log(f"[diag] 第{attempt+1}次点菜单项 → dialog: {dlg}, 请求: {reqs}")
            if dlg:
                break
            # 关掉可能残留的下拉/dialog
            page.keyboard.press("Escape"); page.wait_for_timeout(600)

        browser.close()


if __name__ == "__main__":
    main()