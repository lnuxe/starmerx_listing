"""勘察左侧菜单容器结构，找上架计划入口的真实定位方式。"""
from __future__ import annotations

import re
from pathlib import Path

from playwright.sync_api import sync_playwright

from src.config import load_config, log, ROOT
from src.login import _open_context, is_logged_in
from src.dom import wait_network_idle_light


def main() -> None:
    config = load_config()
    with sync_playwright() as p:
        browser, context = _open_context(p, config, headless=True,
                                         storage=ROOT / config["app"]["storage_state"])
        page = context.new_page()
        page.goto(config["app"]["base_url"], wait_until="domcontentloaded", timeout=60000)
        wait_network_idle_light(page)
        page.wait_for_timeout(2500)
        log(f"[probe] URL: {page.url}")

        # dump 左侧菜单容器的 HTML 结构（限左侧区域）
        out = page.evaluate(
            """() => {
                // 找到包含「销售管理」文本的左侧菜单
                const all = [];
                const find = (el, depth) => {
                    if (depth > 8) return;
                    const cls = (el.className || '').toString();
                    if (typeof cls === 'string' && (cls.includes('menu') || cls.includes('aside') || cls.includes('sidebar'))) {
                        all.push({depth, tag: el.tagName.toLowerCase(), cls: cls.slice(0, 50),
                                  txt: (el.innerText||'').replace(/\\s+/g,' ').slice(0, 80)});
                    }
                    [...el.children].forEach(c => find(c, depth+1));
                };
                find(document.body, 0);
                // 左侧区域过滤：x 坐标 < 250
                const left = all.filter(o => true);
                return left.slice(0, 40).map(o =>
                    `${'  '.repeat(o.depth)}<${o.tag}> .${o.cls.split(' ')[0]} "${o.txt}"`
                ).join('\\n');
            }"""
        )
        runtime = ROOT / "runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        dump = runtime / "probe_sidebar_tree.txt"
        dump.write_text(out, encoding="utf-8")
        log(f"[probe] 侧边栏结构已保存: {dump}")
        browser.close()


if __name__ == "__main__":
    main()