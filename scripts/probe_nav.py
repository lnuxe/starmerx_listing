"""勘察左侧导航完整结构，找上架计划入口。"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from src.config import load_config, log, ROOT
from src.login import _open_context, is_logged_in
from src.dom import wait_network_idle_light

RE_HASH = re.compile(r"#.*")


def log_probe(msg: str) -> None:
    log(f"[probe] {msg}")


def main() -> None:
    config = load_config()
    with sync_playwright() as p:
        browser, context = _open_context(p, config, headless=True,
                                         storage=ROOT / config["app"]["storage_state"])
        page = context.new_page()
        page.goto(config["app"]["base_url"], wait_until="domcontentloaded", timeout=60000)
        wait_network_idle_light(page)
        page.wait_for_timeout(3000)
        log_probe(f"URL: {page.url}")
        if not is_logged_in(page):
            log_probe("✗ 未登录")
            browser.close()
            return

        # dump 左侧菜单所有文字 + 链接
        out = page.evaluate(
            """() => {
                const out = [];
                // 左侧 el-menu 菜单项
                const items = document.querySelectorAll('.el-menu .el-menu-item, .el-menu .el-sub-menu__title, .el-menu .el-sub-menu');
                items.forEach((m, i) => {
                    const txt = (m.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 40);
                    const r = m.getBoundingClientRect();
                    if (!txt || (r.width===0 && r.height===0)) return;
                    const href = m.closest('a') ? m.closest('a').getAttribute('href') : '';
                    out.push(`${m.tagName.toLowerCase()}.${(m.className||'').split(' ')[0]} ${txt} href=${href||'-'}`);
                });
                if (!out.length) {
                    // 兜底：所有可见文本
                    document.querySelectorAll('li, a, div').forEach((m) => {
                        const txt = (m.innerText||'').trim().replace(/\\s+/g,' ').slice(0,30);
                        const r = m.getBoundingClientRect();
                        if (txt && r.width>0 && r.height>0) out.push(`<${m.tagName.toLowerCase()}> ${txt}`);
                    });
                }
                return out.slice(0, 200).join('\\n');
            }"""
        )
        runtime = ROOT / "runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        dump = runtime / "probe_nav.txt"
        dump.write_text(out, encoding="utf-8")
        log_probe(f"菜单清单已保存: {dump}（{len(out.splitlines())} 条）")
        shot = runtime / "probe_nav.png"
        page.screenshot(path=str(shot), full_page=True)
        log_probe(f"截图: {shot}")
        browser.close()


if __name__ == "__main__":
    main()