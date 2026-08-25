"""诊断脚本 v2：dump 美区视图下 市场/店铺/渠道 选择器的 disabled 链，定位品类解锁前置。只读+切tab。"""
from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

from src.config import load_config, log, ROOT
from src.login import _open_context, is_logged_in
from src.dom import wait_network_idle_light


def main() -> None:
    config = load_config()

    with sync_playwright() as p:
        browser, context = _open_context(p, config, headless=config["app"]["headless"],
                                         storage=ROOT / config["app"]["storage_state"])
        page = context.new_page()
        if not is_logged_in(page):
            log("[diag2] ✗ 未登录")
            browser.close()
            sys.exit(1)

        pool = config["product_pool"]
        page.goto(pool["url"], wait_until="domcontentloaded", timeout=60000)
        wait_network_idle_light(page)
        page.wait_for_timeout(3000)
        log(f"[diag2] URL: {page.url[:120]}")

        # 点击美区产品池 tab
        page.evaluate(
            """() => {
                const el = [...document.querySelectorAll('.el-tabs__item')]
                    .find(e => (e.innerText||'').includes('美区产品池'));
                if (el && !el.className.includes('is-active')) el.click();
            }"""
        )
        page.wait_for_timeout(2500)

        # dump 品类前置链路：市场 / 店铺 / 品类 选择器状态
        chain = page.evaluate(
            """() => {
                const out = [];
                document.querySelectorAll('.el-cascader, .el-select, .el-cascader__search-input').forEach((c, i) => {
                    const inp = c.querySelector('.el-input__inner') || c;
                    const r = c.getBoundingClientRect();
                    const t = (c.innerText||'').trim().slice(0,30);
                    out.push({
                        i, tag: c.tagName, ph: (inp&&inp.placeholder)||'',
                        val: (inp&&inp.value)||'', txt: t,
                        w: Math.round(r.width), h: Math.round(r.height),
                        visible: c.offsetParent !== null && r.width>0,
                        disabled: c.classList.contains('is-disabled')
                    });
                });
                return out;
            }"""
        )
        log(f"[diag2] 选择器链路: {chain}")

        # dump 品类级联容器（品类专用）
        cat = page.evaluate(
            """() => {
                const out = [];
                document.querySelectorAll('.el-cascader').forEach((c, i) => {
                    const inp = c.querySelector('.el-input__inner');
                    const r = c.getBoundingClientRect();
                    const t = (inp&&inp.placeholder)||'';
                    if (!t.includes('品类')) return;
                    out.push({
                        i, ph: t, val: (inp&&inp.value)||'',
                        w: Math.round(r.width), h: Math.round(r.height),
                        visible: c.offsetParent !== null && r.width>0,
                        disabled: c.classList.contains('is-disabled')
                    });
                });
                return out;
            }"""
        )
        log(f"[diag2] 品类选择器: {cat}")

        # dump 市场/店铺 的可见选项（点击市场选择器展开）
        market = page.evaluate(
            """() => {
                const inp = [...document.querySelectorAll('.el-select__wrapper, .el-select')]
                    .find(e => (e.querySelector('.el-input__inner')?.placeholder||'').includes('市场'));
                if (!inp) return 'no market';
                inp.click();
                return 'clicked';
            }"""
        )
        log(f"[diag2] 点击市场: {market}")
        page.wait_for_timeout(1500)
        opts = page.evaluate(
            """() => {
                const out = [];
                document.querySelectorAll('.el-select-dropdown__item, .el-cascader-node').forEach((e) => {
                    const r = e.getBoundingClientRect();
                    if (e.offsetParent === null || r.width===0) return;
                    out.push((e.innerText||'').trim().slice(0,20));
                });
                return out;
            }"""
        )
        log(f"[diag2] 市场展开后可见选项: {opts}")
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)

        # ── 深入诊断「开发负责人」：点击后 dump 所有下拉/popper 内容 ──
        page.evaluate(
            """() => {
                const inp = [...document.querySelectorAll('.el-select__wrapper, .el-select')]
                    .find(e => (e.querySelector('.el-input__inner')?.placeholder||'').includes('开发负责人'));
                if (!inp) return false;
                inp.click();
                return true;
            }"""
        )
        log("[diag2] 已点击开发负责人")
        page.wait_for_timeout(2500)

        # dump 所有 el-select-dropdown / el-popper 内容（含虚拟滚动）
        dev = page.evaluate(
            """() => {
                const out = [];
                document.querySelectorAll('.el-select-dropdown, .el-popper, '
                    + '.el-select-dropdown__wrap, .el-scrollbar__view').forEach((e) => {
                    const r = e.getBoundingClientRect();
                    const vis = e.offsetParent !== null && r.width>0;
                    if (!vis) return;
                    const items = [...e.querySelectorAll('.el-select-dropdown__item')]
                        .map(x => (x.innerText||'').trim());
                    const text = (e.innerText||'').trim().slice(0,120);
                    out.push({ tag: e.tagName, cls: e.className.slice(0,40),
                        items: items.slice(0,10), text });
                });
                return out;
            }"""
        )
        log(f"[diag2] 开发负责人下拉内容: {dev}")

        shot2 = ROOT / "runtime" / "diag2_dev.png"
        page.screenshot(path=str(shot2), full_page=True)
        log(f"[diag2] 开发负责人展开截图: {shot2}")
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)

        shot = ROOT / "runtime" / "diag2_market.png"
        page.screenshot(path=str(shot), full_page=True)
        log(f"[diag2] 截图: {shot}")

        page.wait_for_timeout(3000)
        browser.close()


if __name__ == "__main__":
    main()