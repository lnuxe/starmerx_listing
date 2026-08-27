"""临时探针：直接调用 phase2._snap_row0 看它到底返回什么。"""
from __future__ import annotations

import json
import sys

from playwright.sync_api import sync_playwright

from src.config import load_config, log, ROOT
from src.login import _open_context, is_logged_in
from src.phase2 import _open_plan_page, _open_profit_drawer, _snap_row0


def main() -> None:
    config = load_config()
    with sync_playwright() as p:
        browser, context = _open_context(
            p, config, headless=config["app"]["headless"],
            storage=ROOT / config["app"]["storage_state"],
        )
        page = context.new_page()
        if not is_logged_in(page):
            log("✗ 未登录"); browser.close(); sys.exit(1)

        _open_plan_page(page, config)
        page.wait_for_timeout(2000)
        try:
            page.locator(".vxe-table--body-wrapper tr").first.wait_for(
                state="attached", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(1000)

        _open_profit_drawer(page, row_idx=0)
        page.wait_for_timeout(1500)

        # 点搜索
        page.evaluate(
            """() => {
                const roots = [...document.querySelectorAll(
                    '.el-drawer:not([style*="display: none"]), '
                    + '.el-dialog:not([style*="display: none"])')]
                    .filter(r => r.offsetParent !== null
                        || r.getBoundingClientRect().width > 0);
                const root = roots.find(r => (r.innerText||'').includes('保存算价'))
                    || roots[0];
                if (!root) return false;
                const btn = [...root.querySelectorAll('button')]
                    .find(b => (b.innerText||'').trim() === '搜索');
                if (!btn) return false;
                btn.click(); return true;
            }"""
        )
        for _ in range(20):
            page.wait_for_timeout(1000)
            s = _snap_row0(page)
            if s.get("margin") is not None or s.get("note") not in (None, "no rows"):
                break

        s0 = _snap_row0(page)
        log("=== _snap_row0 返回 ===")
        log(json.dumps(s0, ensure_ascii=False, indent=2))

        shot = ROOT / "runtime" / "probe_snap_row0.png"
        page.screenshot(path=str(shot), full_page=True)
        log(f"截图: {shot}")
        browser.close()


if __name__ == "__main__":
    main()