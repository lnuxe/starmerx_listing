"""验证活动营销费占比设50%。复用probe_activity_fee稳定导航。"""
from __future__ import annotations
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import load_config, log, ROOT
from src.login import _open_context
from src.dom import wait_network_idle_light

SEL_MENU_SALES = "text=销售管理"
SEL_SUB_LISTING_PLAN = "text=上架计划"

def main():
    config = load_config()
    with sync_playwright() as p:
        browser, context = _open_context(p, config, headless=False,
                                         storage=ROOT / config["app"]["storage_state"])
        page = context.new_page()
        page.goto(config["app"]["base_url"], wait_until="domcontentloaded", timeout=60000)
        wait_network_idle_light(page)
        page.wait_for_timeout(2500)
        sidebar = page.locator(".sidebar-container")
        sidebar.locator(SEL_MENU_SALES).first.click(timeout=8000)
        page.wait_for_timeout(1500)
        sidebar.locator(SEL_SUB_LISTING_PLAN).first.click(timeout=8000)
        page.wait_for_timeout(2500)

        rc = 0
        for _ in range(30):
            rc = page.evaluate("""() => {
                const t = document.querySelector('.vxe-table');
                if (!t) return 0;
                return [...t.querySelectorAll('button')]
                    .filter(b => (b.innerText||'').trim() === '编辑').length;
            }""")
            if rc and rc >= 3:
                break
            page.wait_for_timeout(1000)
        log(f"[verify] 主表编辑按钮数: {rc}")
        if rc < 3:
            log("[verify] ✗ 主表未加载")
            browser.close(); sys.exit(1)

        page.locator(".vxe-table button:has-text('编辑')").nth(2).click(timeout=8000)
        for _ in range(30):
            has = page.evaluate("""() => {
                const r = document.querySelector('.el-drawer');
                return r && (r.innerText||'').includes('保存算价');
            }""")
            if has: break
            page.wait_for_timeout(1000)

        page.evaluate("""() => {
            const rs = [...document.querySelectorAll('.el-drawer:not([style*="display: none"]), .el-dialog:not([style*="display: none"])')]
                .filter(r => r.offsetParent !== null || r.getBoundingClientRect().width > 0);
            const root = rs.find(r => (r.innerText||'').includes('保存算价')) || rs[0];
            const btn = root && [...root.querySelectorAll('button')].find(b => (b.innerText||'').trim() === '搜索');
            if (btn) btn.click();
        }""")
        has_data = False
        for _ in range(25):
            has_data = page.evaluate("""() => {
                const r = document.querySelector('.el-drawer');
                if (!r) return false;
                return [...r.querySelectorAll('.vxe-input--inner')].some(e => e.getBoundingClientRect().y > 500);
            }""")
            if has_data: break
            page.wait_for_timeout(1000)
        log(f"[verify] 抽屉已开，测算数据: {'✓' if has_data else '✗'}")
        page.wait_for_timeout(1500)

        before = page.evaluate("""() => {
            const rs = [...document.querySelectorAll('.el-drawer:not([style*="display: none"]), .el-dialog:not([style*="display: none"])')]
                .filter(r => r.offsetParent !== null || r.getBoundingClientRect().width > 0);
            const root = rs.find(r => (r.innerText||'').includes('保存算价')) || rs[0];
            if (!root) return { note: 'no drawer' };
            const row = [...root.querySelectorAll('.vxe-body--row, tr.vxe-row')]
                .filter(r => r.getBoundingClientRect().width > 0)[0];
            if (!row) return { note: 'no row' };
            const inputs = [...row.querySelectorAll('input')].filter(e => e.getBoundingClientRect().width > 0);
            if (inputs.length < 5) return { note: 'few inputs', n: inputs.length };
            const fee = inputs[4]; fee.id = '__mkt_fee__';
            const margin = inputs[2]; margin.id = '__mkt_margin__';
            return { margin: margin.value, fee: fee.value, fee_cell: fee.closest('td').innerText };
        }""")
        log(f"[verify] 活动营销费(改前): {before}")

        page.fill("#__mkt_fee__", "50")
        page.wait_for_timeout(300)
        page.keyboard.press("Enter")
        page.wait_for_timeout(300)
        page.evaluate("""() => {
            const rs = [...document.querySelectorAll('.el-drawer:not([style*="display: none"]), .el-dialog:not([style*="display: none"])')]
                .filter(r => r.offsetParent !== null || r.getBoundingClientRect().width > 0);
            const root = rs.find(r => (r.innerText||'').includes('保存算价')) || rs[0];
            const btn = root && [...root.querySelectorAll('button')].find(b => (b.innerText||'').trim() === '重新测算');
            if (btn) btn.click();
        }""")
        for _ in range(20):
            busy = page.evaluate("""() => {
                const r = document.querySelector('.el-drawer');
                if (!r) return false;
                const m = r.querySelector('.el-loading-mask, .vxe-loading');
                return m && m.getBoundingClientRect().width > 0;
            }""")
            if not busy: break
            page.wait_for_timeout(500)
        page.wait_for_timeout(1500)

        after = page.evaluate("""() => {
            const fee = document.getElementById('__mkt_fee__');
            const margin = document.getElementById('__mkt_margin__');
            const row = margin ? margin.closest('tr') : null;
            const text = row ? row.innerText : '';
            const m = text.match(/个人:\\s*[\\d.]+\\s+([\\d.]+)%/);
            return { margin: margin ? margin.value : null, fee: fee ? fee.value : null,
                     fee_cell: fee ? fee.closest('td').innerText : null, personal_pct: m ? m[1] : null };
        }""")
        log(f"[verify] 活动营销费(填50后): {after}")
        fee_val = after.get("fee")
        ok = fee_val is not None and abs(float(fee_val) - 50.0) < 0.1
        log(f"[verify] {'✓ 活动营销费占比已设为 50%' if ok else '✗ 未达 50%'}")

        shot = ROOT / "runtime" / "verify_marketing_fee_50.png"
        page.screenshot(path=str(shot), full_page=True)
        log(f"[verify] 截图: {shot}")
        browser.close()

if __name__ == "__main__":
    main()