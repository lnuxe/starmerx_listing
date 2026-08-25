"""诊断脚本：dump 产品池页面真实状态，定位标签/级联不可见原因。只读不改。"""
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
            log("[diag] ✗ 未登录")
            browser.close()
            sys.exit(1)

        pool = config["product_pool"]
        page.goto(pool["url"], wait_until="domcontentloaded", timeout=60000)
        wait_network_idle_light(page)
        page.wait_for_timeout(3000)
        log(f"[diag] URL: {page.url[:200]}")

        # dump 所有 tab 文本（美区/多渠道/产品池等）
        tabs = page.evaluate(
            """() => {
                const els = document.querySelectorAll(
                    '.el-tabs__item, .el-tab-pane, [role=tab], .vxe-tab, li, span');
                const seen = new Set();
                const out = [];
                for (const e of els) {
                    const t = (e.innerText||'').trim();
                    if (t && t.length <= 12 && !seen.has(t)) {
                        const r = e.getBoundingClientRect();
                        const vis = e.offsetParent !== null && r.width > 0;
                        if (vis) { seen.add(t); out.push(t); }
                    }
                }
                return out;
            }"""
        )
        log(f"[diag] 可见 tab/文本: {tabs}")

        # 专门定位 el-tabs__item（产品池分类 tab）
        pool_tabs = page.evaluate(
            """() => {
                const out = [];
                document.querySelectorAll('.el-tabs__item').forEach((e, i) => {
                    const r = e.getBoundingClientRect();
                    out.push({
                        i, txt: (e.innerText||'').trim(),
                        cls: e.className, w: Math.round(r.width), h: Math.round(r.height),
                        visible: e.offsetParent !== null && r.width>0
                    });
                });
                return out;
            }"""
        )
        log(f"[diag] el-tabs__item: {pool_tabs}")

        # dump「多渠道」相关的可点击元素
        chan = page.evaluate(
            """() => {
                const out = [];
                document.querySelectorAll('.el-radio-button, .el-checkbox-button, '
                    + '.el-radio, .el-checkbox, [class*=channel], [class*=Channel]').forEach((e) => {
                    const t = (e.innerText||'').trim();
                    if (!t) return;
                    const r = e.getBoundingClientRect();
                    out.push({
                        tag: e.tagName, cls: e.className, txt: t.slice(0,20),
                        w: Math.round(r.width), visible: e.offsetParent !== null && r.width>0
                    });
                });
                return out;
            }"""
        )
        log(f"[diag] 渠道相关元素: {chan}")

        # 若当前已是美区视图，dump 品类选择器可见性
        page.evaluate("""() => {
            const el = [...document.querySelectorAll('.el-tabs__item')]
                .find(e => (e.innerText||'').includes('美区产品池'));
            if (el && !el.className.includes('is-active')) el.click();
        }""")
        page.wait_for_timeout(2000)
        cat2 = page.evaluate(
            """() => {
                const out = [];
                document.querySelectorAll('.el-cascader').forEach((c, i) => {
                    const inp = c.querySelector('.el-input__inner');
                    const r = c.getBoundingClientRect();
                    out.push({
                        i, ph: (inp&&inp.placeholder)||'', val: (inp&&inp.value)||'',
                        w: Math.round(r.width), h: Math.round(r.height),
                        visible: c.offsetParent !== null && r.width>0,
                        disabled: c.classList.contains('is-disabled')
                    });
                });
                return out;
            }"""
        )
        log(f"[diag] 切到美区后 品类选择器: {cat2}")

        # 品类选择器
        cat = page.evaluate(
            """() => {
                const out = [];
                document.querySelectorAll('.el-cascader').forEach((c, i) => {
                    const inp = c.querySelector('.el-input__inner');
                    const r = c.getBoundingClientRect();
                    out.push({
                        i, ph: (inp&&inp.placeholder)||'', val: (inp&&inp.value)||'',
                        w: Math.round(r.width), h: Math.round(r.height),
                        visible: c.offsetParent !== null && r.width>0,
                        disabled: c.classList.contains('is-disabled')
                    });
                });
                return out;
            }"""
        )
        log(f"[diag] 品类选择器: {cat}")

        # 记录数
        rec = page.evaluate(
            """() => {
                const m = document.body.innerText.match(/共\\s*([\\d,]+)\\s*条/);
                return m ? m[1] : null;
            }"""
        )
        log(f"[diag] 记录数: {rec}")

        shot = ROOT / "runtime" / "diag_pool.png"
        page.screenshot(path=str(shot), full_page=True)
        log(f"[diag] 截图: {shot}")

        page.wait_for_timeout(3000)
        browser.close()


if __name__ == "__main__":
    main()