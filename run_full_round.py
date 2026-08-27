"""完整跑一轮 Phase2 利润算价，每个关键节点截图归纳到 runtime/本轮截图/。

截图清单（按执行顺序）：
  01_上架计划列表.png
  02_打开利润抽屉.png
  03_点搜索后_测算行.png
  04_改活动营销费50后_重新测算.png
  05_二分搜索_第1步.png
  06_二分搜索_第3步.png
  07_二分搜索_最后一步.png
  08_利润列_公司个人详情.png
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from src.config import load_config, log, ROOT
from src.login import _open_context, is_logged_in
from src.phase2 import _open_plan_page, _open_profit_drawer, _snap_row0, _recalc_profit

SHOT_DIR = ROOT / "runtime" / "本轮截图"


def shot(page, name: str) -> None:
    p = SHOT_DIR / name
    page.screenshot(path=str(p), full_page=True)
    log(f"[截图] {name}")


def main() -> None:
    config = load_config()
    v = config["verification"]
    with sync_playwright() as p:
        browser, context = _open_context(
            p, config, headless=config["app"]["headless"],
            storage=ROOT / config["app"]["storage_state"],
        )
        page = context.new_page()
        if not is_logged_in(page):
            log("✗ 未登录"); browser.close(); sys.exit(1)

        # 1. 进入上架计划页
        _open_plan_page(page, config)
        page.wait_for_timeout(2000)
        try:
            page.locator(".vxe-table--body-wrapper tr").first.wait_for(
                state="attached", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(1000)
        shot(page, "01_上架计划列表.png")

        # 2. 打开首行利润抽屉
        ok = _open_profit_drawer(page, row_idx=0)
        log(f"打开抽屉: {ok}")
        page.wait_for_timeout(1500)
        shot(page, "02_打开利润抽屉.png")

        # 3. 点搜索加载测算行
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
        for _ in range(25):
            if _snap_row0(page).get("margin") is not None:
                break
            page.wait_for_timeout(1000)
        shot(page, "03_点搜索后_测算行.png")

        s0 = _snap_row0(page)
        log(f"首行快照: margin={s0.get('margin')} mkt_fee={s0.get('mkt_fee')} "
            f"personal_pct={s0.get('personal_pct')}")

        # 4. 改活动营销费 50% + 重新测算
        mkt_rate = v["activity_marketing_rate"] * 100
        log(f"活动营销费占比: 当前 {s0.get('mkt_fee')}% → 目标 {mkt_rate}%")
        page.fill("#__mkt_fee__", f"{mkt_rate:.2f}")
        page.keyboard.press("Enter")
        page.wait_for_timeout(300)
        _recalc_profit(page)
        page.wait_for_timeout(800)
        shot(page, "04_改活动营销费50后_重新测算.png")

        s1 = _snap_row0(page)
        log(f"改活动营销费后: margin={s1.get('margin')} mkt_fee={s1.get('mkt_fee')} "
            f"personal_pct={s1.get('personal_pct')}")

        # 5. 手动做几步公司利润率调整，观察个人利润率是否联动
        log("=== 开始观察：改公司利润率 → 个人利润率是否联动 ===")
        test_margins = [40, 30, 20, 10, 5]
        for idx, m in enumerate(test_margins):
            page.fill("#__margin2__", f"{m:.2f}")
            page.keyboard.press("Enter")
            page.wait_for_timeout(300)
            _recalc_profit(page)
            page.wait_for_timeout(800)
            s = _snap_row0(page)
            log(f"公司利润率={m}% → 个人利润率={s.get('personal_pct')}% "
                f"(mkt_fee={s.get('mkt_fee')})")
            if idx == 1:
                shot(page, "05_公司利润率30_观察.png")
            if idx == 3:
                shot(page, "06_公司利润率10_观察.png")

        # 最后一步
        shot(page, "07_公司利润率5_最终.png")

        # 6. 横向滚动到利润列，截详情
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
        shot(page, "08_横向滚动到利润列_公司个人详情.png")

        log("=== 本轮截图已归纳到 runtime/本轮截图/ ===")
        browser.close()


if __name__ == "__main__":
    main()