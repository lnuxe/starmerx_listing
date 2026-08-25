"""诊断脚本 v3：尝试解锁品类选择器，定位前置链。
策略：点「开发负责人」选第一个值 → 检查「开发部门」「品类」是否解禁。"""
from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

from src.config import load_config, log, ROOT
from src.login import _open_context, is_logged_in
from src.dom import wait_network_idle_light


def _cat_state(page):
    return page.evaluate(
        """() => {
            const out = [];
            document.querySelectorAll('.el-cascader').forEach((c, i) => {
                const inp = c.querySelector('.el-input__inner');
                const r = c.getBoundingClientRect();
                const ph = (inp&&inp.placeholder)||'';
                if (!ph.includes('品类')) return;
                out.push({ i, ph, val: (inp&&inp.value)||'',
                    visible: c.offsetParent !== null && r.width>0,
                    disabled: c.classList.contains('is-disabled') });
            });
            return out;
        }"""
    )


def _dev_owner_state(page):
    return page.evaluate(
        """() => {
            const out = [];
            document.querySelectorAll('.el-cascader, .el-select').forEach((c, i) => {
                const inp = c.querySelector('.el-input__inner');
                const r = c.getBoundingClientRect();
                const ph = (inp&&inp.placeholder)||'';
                if (ph !== '开发负责人' && ph !== '开发部门') return;
                out.push({ i, ph, val: (inp&&inp.value)||'',
                    visible: c.offsetParent !== null && r.width>0,
                    disabled: c.classList.contains('is-disabled') });
            });
            return out;
        }"""
    )


def main() -> None:
    config = load_config()

    with sync_playwright() as p:
        browser, context = _open_context(p, config, headless=config["app"]["headless"],
                                         storage=ROOT / config["app"]["storage_state"])
        page = context.new_page()
        if not is_logged_in(page):
            log("[diag3] ✗ 未登录")
            browser.close()
            sys.exit(1)

        pool = config["product_pool"]
        page.goto(pool["url"], wait_until="domcontentloaded", timeout=60000)
        wait_network_idle_light(page)
        page.wait_for_timeout(3000)

        # 切美区
        page.evaluate(
            """() => {
                const el = [...document.querySelectorAll('.el-tabs__item')]
                    .find(e => (e.innerText||'').includes('美区产品池'));
                if (el && !el.className.includes('is-active')) el.click();
            }"""
        )
        page.wait_for_timeout(2500)
        log(f"[diag3] 切美区后 品类: {_cat_state(page)}")
        log(f"[diag3] 开发负责人/部门: {_dev_owner_state(page)}")

        # 点击「开发负责人」下拉
        clicked = page.evaluate(
            """() => {
                const el = [...document.querySelectorAll('.el-select, .el-cascader')]
                    .find(e => (e.querySelector('.el-input__inner')?.placeholder||'') === '开发负责人');
                if (!el) return false;
                const inp = el.querySelector('.el-input__inner');
                const r = el.getBoundingClientRect();
                el.dispatchEvent(new MouseEvent('mousedown', {bubbles:true}));
                return true;
            }"""
        )
        log(f"[diag3] 点开发负责人: {clicked}")
        page.wait_for_timeout(1500)

        # dump 下拉选项
        opts = page.evaluate(
            """() => {
                const out = [];
                document.querySelectorAll('.el-select-dropdown__item, '
                    + '.el-cascader-node, .el-select-dropdown').forEach((e) => {
                    const r = e.getBoundingClientRect();
                    if (e.offsetParent === null || r.width===0) return;
                    const t = (e.innerText||'').trim();
                    if (t && t.length<20) out.push(t);
                });
                return out;
            }"""
        )
        log(f"[diag3] 开发负责人下拉选项: {opts[:15]}")

        # 选第一个
        if opts:
            page.evaluate(
                """(txt) => {
                    const els = [...document.querySelectorAll('.el-select-dropdown__item, '
                        + '.el-cascader-node')]
                        .filter(e => (e.innerText||'').trim() === txt && e.offsetParent !== null);
                    if (els[0]) els[0].click();
                }""",
                opts[0],
            )
            page.wait_for_timeout(1500)
            log(f"[diag3] 已选开发负责人={opts[0]}")
            log(f"[diag3] 选后 品类: {_cat_state(page)}")
            log(f"[diag3] 选后 开发负责人/部门: {_dev_owner_state(page)}")

        shot = ROOT / "runtime" / "diag3.png"
        page.screenshot(path=str(shot), full_page=True)
        log(f"[diag3] 截图: {shot}")

        page.wait_for_timeout(3000)
        browser.close()


if __name__ == "__main__":
    main()