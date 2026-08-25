"""勘察工具：在登录态下打开目标页面，dump 页面结构与关键元素。

用于开发期确认真实 DOM 选择器，避免盲写。用法：
    python -m scripts.probe_product_pool [--screenshot NAME]
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from src.config import load_config, log, ROOT
from src.login import _open_context, is_logged_in


def probe(config: dict, url: str, label: str, screenshot: str | None) -> None:
    with sync_playwright() as p:
        browser, context = _open_context(p, config, headless=True,
                                         storage=ROOT / config["app"]["storage_state"])
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)

        if not is_logged_in(page):
            log(f"[probe:{label}] ✗ 未登录，无法勘察（先扫码登录）")
            browser.close()
            return

        log(f"[probe:{label}] URL: {page.url}")
        # 切换到"美区产品池"标签页（否则默认视图可能为空数据）
        try:
            tab = page.locator("text=美区产品池").first
            if tab.count():
                tab.click(timeout=8000)
                log(f"[probe:{label}] 已点击「美区产品池」标签")
        except Exception as e:
            log(f"[probe:{label}] ⚠ 点击美区产品池标签失败: {str(e)[:50]}")
        # 尝试等待 SPA 渲染
        page.wait_for_timeout(4000)

        if screenshot:
            shot = ROOT / "runtime" / f"{screenshot}.png"
            shot.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(shot), full_page=True)
            log(f"[probe:{label}] 截图已保存: {shot}")

        # dump 可交互元素
        out = page.evaluate(
            """() => {
                const els = document.querySelectorAll(
                    'button, a, input, select, [role=tab], [role=button], '
                    + '.vxe-table--header .vxe-header-column'
                );
                const seen = new Set();
                const items = [];
                for (const e of els) {
                    const txt = (e.innerText || e.value || e.placeholder || '')
                        .trim().replace(/\\s+/g, ' ').slice(0, 80);
                    if (!txt || seen.has(txt)) continue;
                    seen.add(txt);
                    const r = e.getBoundingClientRect();
                    if (r.width === 0 && r.height === 0) continue;
                    items.push(`${e.tagName.toLowerCase()}<${e.className.split(' ')[0]||''}> ${txt}`);
                }
                return items.slice(0, 400).join('\\n');
            }"""
        )
        runtime = ROOT / "runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        dump = runtime / f"probe_{label}.txt"
        dump.write_text(out, encoding="utf-8")
        log(f"[probe:{label}] 元素清单已保存: {dump}（{len(out.splitlines())} 条）")

        browser.close()


def main() -> None:
    config = load_config()
    url = config["product_pool"]["url"]
    args = sys.argv[1:]
    label = "product_pool"
    screenshot = None
    if args:
        label = args[0]
    if "--screenshot" in args:
        i = args.index("--screenshot")
        screenshot = args[i + 1] if i + 1 < len(args) else label
    probe(config, url, label, screenshot)


if __name__ == "__main__":
    main()