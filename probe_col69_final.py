"""临时探针：终极确认「活动营销费」列 col_69 的完整结构，判断 input 填金额还是占比。

策略：直接读 col_69 的 outerHTML + 所有 input 及其 suffix，横向滚动到该列后截图。
"""
from __future__ import annotations

import json
import sys

from playwright.sync_api import sync_playwright

from src.config import load_config, log, ROOT
from src.login import _open_context, is_logged_in
from src.phase2 import _open_plan_page, _open_profit_drawer


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
        page.wait_for_timeout(5000)

        # 终极 dump：col_69 完整 outerHTML + 相邻 col_68(广告费) 对照
        dump = page.evaluate(
            """() => {
                const roots = [...document.querySelectorAll(
                    '.el-drawer:not([style*="display: none"]), '
                    + '.el-dialog:not([style*="display: none"])')]
                    .filter(r => r.offsetParent !== null
                        || r.getBoundingClientRect().width > 0);
                const root = roots.find(r => (r.innerText||'').includes('保存算价'))
                    || roots[0];
                if (!root) return { note: 'no root' };

                const out = {};
                for (const cid of ['col_58', 'col_68', 'col_69']) {
                    const td = root.querySelector(`td[colid="${cid}"]`);
                    if (!td) { out[cid] = 'no td'; continue; }
                    const inputs = [...td.querySelectorAll('input')].map(e => ({
                        value: e.value,
                        ph: e.placeholder,
                        // 后缀文本（% 或 $）
                        suffix: (e.closest('.vxe-input')?.querySelector('.vxe-input--suffix-icon')?.innerText || ''),
                    }));
                    const spans = [...td.querySelectorAll('span')].map(s => s.innerText.trim()).filter(Boolean);
                    out[cid] = {
                        text: td.innerText,
                        spans,
                        inputs,
                        outerHTML: td.outerHTML,
                    };
                }
                return out;
            }"""
        )
        log(json.dumps(dump, ensure_ascii=False, indent=2))

        # 横向滚动到最右，让活动营销费列可见后截图
        page.evaluate(
            """() => {
                const roots = [...document.querySelectorAll(
                    '.el-drawer:not([style*="display: none"]), '
                    + '.el-dialog:not([style*="display: none"])')]
                    .filter(r => r.offsetParent !== null
                        || r.getBoundingClientRect().width > 0);
                const root = roots.find(r => (r.innerText||'').includes('保存算价'))
                    || roots[0];
                const scroller = root.querySelector('.vxe-table--body-wrapper, .vxe-table--body');
                if (scroller) scroller.scrollLeft = scroller.scrollWidth;
            }"""
        )
        page.wait_for_timeout(1000)
        shot = ROOT / "runtime" / "probe_col69_scrolled.png"
        page.screenshot(path=str(shot), full_page=True)
        log(f"截图: {shot}")
        browser.close()


if __name__ == "__main__":
    main()