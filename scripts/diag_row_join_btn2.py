"""探测2：在美区产品池表格中查找含「加入上架计划」文案的行内按钮（可能文本为空，看 title/子元素/aria）。"""
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
            log("[diag2] ✗ 未登录")
            browser.close()
            sys.exit(1)

        page.goto(pool["url"], wait_until="domcontentloaded", timeout=60000)
        wait_network_idle_light(page)
        safe_click(page, SEL_TAB_US_POOL)
        page.wait_for_timeout(800)
        safe_click(page, SEL_TAB_CHANNEL)
        page.wait_for_timeout(800)
        for attempt in range(3):
            try:
                _open_category(page, config["category"]["system_path"])
                break
            except RuntimeError as e:
                log(f"[diag2] 品类选中失败(第{attempt+1}次): {e}")
                page.keyboard.press("Escape")
                page.wait_for_timeout(1000)
        if pool.get("escape_after_select", True):
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

        # 查找所有含「加入上架计划」文案的元素（button/span/div，含 title/子节点文本）
        found = page.evaluate(
            """() => {
                const hits = [];
                const all = [...document.querySelectorAll('button, span, a, div')]
                    .filter(el => el.offsetParent !== null);
                for (const el of all) {
                    const t = (el.innerText || '').trim();
                    const title = (el.getAttribute('title') || '').trim();
                    const cls = (el.className || '').toString();
                    if (t.includes('加入上架计划') || title.includes('加入上架计划')) {
                        const r = el.getBoundingClientRect();
                        // 只记录叶子（无同样文案的子元素）
                        const childSame = [...el.children].some(c =>
                            ((c.innerText || '').trim().includes('加入上架计划')) ||
                            ((c.getAttribute('title') || '').trim().includes('加入上架计划')));
                        if (!childSame) {
                            hits.push({ tag: el.tagName, t, title, cls: cls.slice(0, 60),
                                        x: Math.round(r.x), y: Math.round(r.y),
                                        w: Math.round(r.width), h: Math.round(r.height) });
                        }
                    }
                }
                return hits;
            }"""
        )
        log("[diag2] 含「加入上架计划」元素:")
        if isinstance(found, list) and found:
            for f in found:
                log(f"[diag2]   <{f['tag']}> t={f['t']!r} title={f['title']!r} cls={f['cls']} @({f['x']},{f['y']}) {f['w']}x{f['h']}")
        else:
            log(f"[diag2]   {found}")

        # 额外：输出表格每行的「操作」列 cell 内部结构（前 2 行）
        ops = page.evaluate(
            """() => {
                const rows = [...document.querySelectorAll(
                    '.vxe-table--body-wrapper tr, .vxe-table--fixed-right-wrapper tr')]
                    .filter(r => r.offsetParent !== null);
                const out = [];
                for (let ri = 0; ri < Math.min(rows.length, 2); ri++) {
                    const cells = [...rows[ri].querySelectorAll('td')];
                    const opCells = cells.map((c, ci) => {
                        const r = c.getBoundingClientRect();
                        const txt = (c.innerText || '').trim();
                        return { ci, txt: txt.slice(0, 30),
                                 x: Math.round(r.x), w: Math.round(r.width) };
                    }).filter(c => c.txt.includes('加入') || c.txt.includes('计算') || c.txt.includes('操作'));
                    out.push({ row: ri, opCells });
                }
                return out;
            }"""
        )
        log("[diag2] 操作列cell:")
        if isinstance(ops, list):
            for o in ops:
                log(f"[diag2]   {o}")

        browser.close()


if __name__ == "__main__":
    main()