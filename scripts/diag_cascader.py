"""诊断脚本 v4：验证 el-cascader 节点点击后 value 是否回填，并测试搜索式选中。"""
from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

from src.config import load_config, log, ROOT
from src.login import _open_context, is_logged_in
from src.dom import wait_network_idle_light


def _cat_input(page):
    """读品类 el-cascader 的 input value 和显示文本。"""
    return page.evaluate(
        """() => {
            let vis = null;
            document.querySelectorAll('.el-cascader').forEach((c) => {
                const inp = c.querySelector('.el-input__inner');
                const ph = (inp && inp.placeholder) || '';
                const r = c.getBoundingClientRect();
                if (ph.includes('品类') && c.offsetParent !== null && r.width > 0) vis = c;
            });
            if (!vis) return {note:'no vis cascader'};
            const inp = vis.querySelector('.el-input__inner');
            return {
                val: inp.value,
                cls: vis.className,
                rendered: (vis.querySelector('.el-select__selected-item, .el-cascader__selected-label, .el-tag')?.innerText || '')
            };
        }"""
    )


def main() -> None:
    config = load_config()
    path = config["category"]["system_path"]

    with sync_playwright() as p:
        browser, context = _open_context(p, config, headless=config["app"]["headless"],
                                         storage=ROOT / config["app"]["storage_state"])
        page = context.new_page()
        if not is_logged_in(page):
            log("[diag4] ✗ 未登录")
            browser.close()
            sys.exit(1)

        pool = config["product_pool"]
        page.goto(pool["url"], wait_until="domcontentloaded", timeout=60000)
        wait_network_idle_light(page)
        page.wait_for_timeout(2000)

        # 切美区
        page.evaluate(
            """() => {
                const el = [...document.querySelectorAll('.el-tabs__item')]
                    .find(e => (e.innerText||'').includes('美区产品池'));
                if (el && !el.className.includes('is-active')) el.click();
            }"""
        )
        page.wait_for_timeout(2500)
        log(f"[diag4] 切美区后品类输入: {_cat_input(page)}")

        # 展开品类级联（点击容器中心）
        page.evaluate(
            """() => {
                let vis = null;
                document.querySelectorAll('.el-cascader').forEach((c) => {
                    const inp = c.querySelector('.el-input__inner');
                    const ph = (inp && inp.placeholder) || '';
                    const r = c.getBoundingClientRect();
                    if (ph.includes('品类') && c.offsetParent !== null && r.width > 0) vis = c;
                });
                if (!vis) return;
                const r = vis.getBoundingClientRect();
                vis.dispatchEvent(new MouseEvent('mousedown', {bubbles:true}));
            }"""
        )
        page.wait_for_timeout(1500)
        has_search = page.evaluate(
            "() => !!document.querySelector('.el-cascader__search-input')"
        )
        log(f"[diag4] 展开后是否有搜索框: {has_search}")

        # 逐级点击，每级后读 value 验证回填
        for idx, node_text in enumerate(path, 1):
            before = _cat_input(page)
            clicked = page.evaluate(
                """(t) => {
                    const nodes = [...document.querySelectorAll('.el-cascader-node')]
                        .filter(n => (n.innerText||'').trim() === t && n.offsetParent !== null);
                    if (!nodes.length) return 'no-node';
                    nodes[0].click();
                    return 'ok';
                }""",
                node_text,
            )
            page.wait_for_timeout(900)
            after = _cat_input(page)
            log(f"[diag4] 第{idx}级「{node_text}」: click={clicked} | "
                f"before.val={before.get('val')!r} after.val={after.get('val')!r} "
                f"after.rendered={after.get('rendered')!r}")

        shot = ROOT / "runtime" / "diag4.png"
        page.screenshot(path=str(shot), full_page=True)
        log(f"[diag4] 截图: {shot}")

        page.wait_for_timeout(3000)
        browser.close()


if __name__ == "__main__":
    main()